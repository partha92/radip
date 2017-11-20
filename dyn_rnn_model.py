import tensorflow as tf
import numpy as np
import random
import MDN
from tensorflow.python.ops import nn_ops
#from TF_mods import basic_rnn_seq2seq_with_loop_function
from tensorflow.contrib.legacy_seq2seq.python.ops import seq2seq
from tensorflow.python.framework import ops
from tensorflow.python.ops import clip_ops
import tensorflow.contrib.layers
from recurrent_batchnorm_tensorflow.BN_LSTMCell import BN_LSTMCell
import tensorflow.contrib.seq2seq
import rnn as sketch_rnn


class DynamicRnnSeq2Seq(object):

    def __init__(self, parameters,hyper_search=False):
        #feed_future_data, train, num_observation_steps, num_prediction_steps, batch_size,
        #         rnn_size, num_layers, learning_rate, learning_rate_decay_factor, input_size, max_gradient_norm,
        #        dropout_prob,random_bias,subsample,random_rotate,num_mixtures,model_type):

        # feed_future_data: whether or not to feed the true data into the decoder instead of using a loopback
        #                function. If false, a loopback function is used, feeding the last generated output as the next
        #                decoder input.
        # train: train the model (or test)
        # Subsample: amount of subsampling. IMPORTANT If this is non-one, the input array must be n times longer than usual, as it only subsamples down
        # This is so that the track is not subsampled the same way each track sample.

        #######################################
        # The LSTM Model consists of:
        # Input Linear layer
        # N LSTM layers
        # a linear output layer to convert the LSTM output to MDN format
        #
        # MDN Format:
        # pi mu1 mu2 sigma1 sigma2 rho
        # (repeat for n mixtures)
        #
        # This MDN format is then either used for the loss, or is sampled to get a real value

        #TODO Reorganise code using namespace for better readability
        self.parameters = parameters
        self.max_gradient_norm = parameters['max_gradient_norm']
        self.rnn_size = parameters['rnn_size']
        self.num_layers = parameters['num_layers']
        dtype = tf.float32

        self.batch_size = parameters['batch_size']
        self.input_size = parameters['input_size']
        self.embedding_size = parameters['embedding_size']
        self.observation_steps = parameters['observation_steps']
        self.prediction_steps = parameters['prediction_steps']
        self.dropout_prob = parameters['dropout_prob']
        self.random_bias = parameters['random_bias']
        self.subsample = parameters['subsample']
        self.random_rotate = parameters['random_rotate']
        self.num_mixtures = parameters['num_mixtures']
        self.model_type = parameters['model_type']
        self.num_classes = parameters['num_classes']
        self.first_loss_only =  parameters['first_loss_only']
        self.global_step = tf.Variable(0, trainable=False,name="Global_step")

        self.learning_rate = tf.Variable(float(parameters['learning_rate']), trainable=False, name="Learning_rate")
        min_rate = parameters['learning_rate_min']
        self.learning_rate_decay_op = self.learning_rate.assign(
            ((parameters['learning_rate'] - min_rate) *
            (parameters['learning_rate_decay_factor']**tf.cast(self.global_step,tf.float32))) + min_rate)
        self.network_summaries = []
        keep_prob = 1-self.dropout_prob

        if parameters['model_type'] == 'classifier':
            raise Exception("Error")

        # The output of the multiRNN is the size of rnn_size, and it needs to match the input size, or loopback makes
        #  no sense. Here a single layer without activation function is used, but it can be any number of
        #  non RNN layers / functions
        if self.model_type == 'MDN':
            n_out = 6*self.num_mixtures

        ############## LAYERS ###################################

        # Layer is linear, just to re-scale the LSTM outputs [-1,1] to [-9999,9999]
        # If there is a regularizer, these weights should be excluded?

        with tf.variable_scope('output_proj'):
            o_w = tf.get_variable("proj_w", [self.rnn_size, n_out],
                                  initializer=tf.truncated_normal_initializer(stddev=1.0 / np.sqrt(self.embedding_size)))
            o_b = tf.get_variable("proj_b", [n_out],
                                  initializer=tf.constant_initializer(0.1))
            output_projection = (o_w, o_b)

        with tf.variable_scope('input_scaling'):
            i_s_m = tf.get_variable('in_scale_mean', shape=[self.input_size],trainable=False,initializer=tf.zeros_initializer())
            i_s_s = tf.get_variable('in_scale_stddev', shape=[self.input_size],trainable=False,initializer=tf.ones_initializer())
            scaling_layer = (i_s_m,i_s_s)
            self.scaling_layer = scaling_layer
        with tf.variable_scope('input_embedding_layer'):
            i_w = tf.get_variable("in_w", [self.input_size, self.embedding_size], # Remember, batch_size is automatic
                                  initializer=tf.truncated_normal_initializer(stddev=1.0/np.sqrt(self.embedding_size)))
            i_b = tf.get_variable("in_b", [self.embedding_size],
                                  initializer=tf.constant_initializer(0.1))
            input_layer = (i_w, i_b)

        def _generate_rnn_layer():
            if parameters['RNN_cell'] == "LSTMCell":
                return tf.contrib.rnn.DropoutWrapper(
                                tf.contrib.rnn.LSTMCell(self.rnn_size,state_is_tuple=True,
                                                        use_peepholes=parameters['peephole_connections'])
                                ,output_keep_prob=keep_prob)
            if parameters['RNN_cell'] == "BN_LSTMCell":
                return tf.contrib.rnn.DropoutWrapper(
                                BN_LSTMCell(self.rnn_size,is_training=True,
                                                        use_peepholes=parameters['peephole_connections'])
                                ,output_keep_prob=keep_prob)
            if parameters['RNN_cell'] == "sketch_LSTM":
                return sketch_rnn.LSTMCell(self.rnn_size,
                                           use_recurrent_dropout=True,
                                           dropout_keep_prob=keep_prob)
            if parameters['RNN_cell'] == "sketch_layer_norm":
                return sketch_rnn.LayerNormLSTMCell(self.rnn_size,
                                                    use_recurrent_dropout=True,
                                                    dropout_keep_prob=keep_prob)
            if parameters['RNN_cell'] == "sketch_hyper":
                return sketch_rnn.HyperLSTMCell(self.rnn_size,
                                                use_recurrent_dropout=True,
                                                dropout_keep_prob=keep_prob)

        if self.num_layers > 1:
            self._RNN_layers = tf.contrib.rnn.MultiRNNCell([_generate_rnn_layer() for _ in range(self.num_layers)],state_is_tuple=True)
        else:
            self._RNN_layers = _generate_rnn_layer()

        # Don't double dropout
        #self._RNN_layers = tensorflow.contrib.rnn.DropoutWrapper(self._RNN_layers,output_keep_prob=keep_prob)

        def output_function(output):
            return nn_ops.xw_plus_b(
                        output, output_projection[0], output_projection[1],name="output_projection"
                    )

        def _pad_missing_output_with_zeros(MDN_samples):
            # TODO Should not be needed, as it will occur later outside tensorflow - not anymore! I'm using raw_rnn now
            # Simple hack for now as I cannot get t-1 data for t_0 derivatives easily due to scoping problems.
            # sampled has shape 256,2 - it needs 256,4
            if MDN_samples.shape[1] < scaling_layer[0].shape[0]:
                resized = tf.concat([MDN_samples, tf.zeros(
                    [MDN_samples.shape[0], scaling_layer[0].shape[0] - MDN_samples.shape[1]], dtype=tf.float32)], 1)
            else:
                resized = MDN_samples
            return resized

        def _upscale_sampled_output(sample):
            return tf.add(tf.multiply(sample, scaling_layer[1][0:2]), scaling_layer[0][0:2])

        def _scale_vel_thresh(velocity_thresh):
            _, _, _, speed_sub = tf.split(self.scaling_layer[0], 4, axis=0)
            _, _, _, speed_div = tf.split(self.scaling_layer[1], 4, axis=0)
            return tf.divide(tf.subtract(tf.constant(velocity_thresh, dtype=tf.float32), speed_sub), speed_div)

        def _apply_scaling_and_input_layer(input_data):
            return tf.nn.dropout(tf.nn.relu(
                                            nn_ops.xw_plus_b(
                                                tf.divide(
                                                    tf.subtract(
                                                        input_data, scaling_layer[0]),
                                                    scaling_layer[1]),  # Input scaling
                                                input_layer[0], input_layer[1])),
                                        1-parameters['embedding_dropout'])

        """This was always the biggest side-loading hack.  Because I cannot give an initial state to the decoder
        raw_rnn, its done in the loop function by defining the function here, and pulling variables traditionally 
         outside of functional scope into the function.
         IMPORTANT - the first call to this function is BEFORE the first node, s.t. the cell_output is None check 
         then sets the initial params.

         Loss function - How can I implement this? It needs to go into the loopback function.
         This is because the sequence length is undefined (even though it isn't) and so my standard loss functions are 
         not working."""

        """ Its better to read the simple implementation of dyn_rnn in 
        https://www.tensorflow.org/api_docs/python/tf/nn/raw_rnn. I can just declare some TensorArrays and fill
         them in the middle of the loop."""

        output_ta = (tf.TensorArray(size=self.prediction_steps, dtype=tf.float32),  # Sampled output
                     tf.TensorArray(size=self.prediction_steps, dtype=tf.float32),  # loss
                     tf.TensorArray(size=self.prediction_steps+1, dtype=tf.float32),   # time-1 for derivative loopback
                     tf.TensorArray(size=self.prediction_steps, dtype=tf.float32)) # MDN outputs # Its either real or generated
                                                                                        # depending on feed_future_data
                                                                                        # (always false for now)

        def seq2seq_f(encoder_inputs, decoder_inputs, targets, last_input):
            # returns (self.LSTM_output, self.internal_states)
            target_input_ta = tf.TensorArray(dtype=tf.float32, size=len(targets))

            for j in range(len(decoder_inputs)):
                target_input_ta = target_input_ta.write(j, targets[j])

            """ First this runs the encoder, then it saves the last internal RNN c state, and passes that into the
            loop parameter as the initial condition. Then it runs the decoder."""

            with tf.variable_scope('seq2seq_encoder'):
                # So I have a list of len(time) of Tensors of shape (batch, RNN dim)
                reordered_encoder_inputs = tf.stack(encoder_inputs,axis=1)
                encoder_outputs, last_enc_state = tf.nn.dynamic_rnn(self._RNN_layers,
                                                                    inputs=reordered_encoder_inputs,
                                                                    dtype=tf.float32)

            def loop_fn(time, cell_output, cell_state, loop_state):
                emit_output = cell_output

                if cell_output is None:
                    # Set initial params
                    next_cell_state = last_enc_state
                    # I have defined last 'encoder input' as actually the first decoder input. It is data for time T_0
                    next_input = decoder_inputs[0]  # Encoder inputs already have input layer applied
                    next_loop_state = (output_ta[0],
                                       output_ta[1],
                                       output_ta[2].write(time, last_input),
                                       output_ta[3])
                else:
                    next_cell_state = cell_state
                    projected_output = output_function(cell_output)
                    sampled = MDN.sample(projected_output)
                    upscale_sampled = _upscale_sampled_output(sampled)
                    if self.parameters['input_mask'][2:4] == [0,0]:
                        next_sampled_input = _pad_missing_output_with_zeros(upscale_sampled)
                    else:
                        next_sampled_input = MDN.compute_derivates(loop_state[2].read(time-1), upscale_sampled,
                                                                   self.parameters['input_columns'],
                                                                   self.parameters['velocity_threshold'])
                    #next_sampled_input = _upscale_sampled_output(next_sampled_input)
                    prev_target_ta = target_input_ta.read(time - 1) # Only allowed to call read() once. Dunno why.
                    next_datapoint = next_sampled_input # tf.cond(feed_forward, lambda: prev_target_ta, lambda: next_sampled_input)
                    next_input = _apply_scaling_and_input_layer(next_datapoint)
                    # That dotted loopy line in the diagram

                    loss = MDN.lossfunc_wrapper(prev_target_ta, projected_output)
                    next_loop_state = (loop_state[0].write(time - 1, next_sampled_input),
                                       loop_state[1].write(time - 1, loss),
                                       loop_state[2].write(time, next_datapoint),
                                       loop_state[3].write(time - 1, MDN.upscale_and_resolve_mixtures(projected_output, scaling_layer)))
                                        #Its an off by one error I'd rather solve with a new array for readability

                elements_finished = (
                    time >= self.prediction_steps)    # whether or not this RNN in the batch has declared itself done

                return (elements_finished, next_input, next_cell_state, emit_output, next_loop_state)

            with tf.variable_scope('seq2seq_decoder'):
                from tensorflow.python.ops.rnn import _transpose_batch_time
                emit_ta, final_state, loop_state_ta = tf.nn.raw_rnn(self._RNN_layers, loop_fn)
                # Here emit_ta should contain all the MDN's for each timestep. To confirm.
                output_sampled = _transpose_batch_time(loop_state_ta[0].stack())
                losses = _transpose_batch_time(loop_state_ta[1].stack())
                MDN_output = _transpose_batch_time(loop_state_ta[3].stack())

            return output_sampled, tf.reduce_sum(losses,axis=1)/len(self.decoder_inputs), final_state, MDN_output


        ################# FEEDS SECTION #######################
        # Feeds for inputs.
        self.observation_inputs = []
        self.future_inputs = []
        self.target_weights = []
        targets = []

        # TODO REFACTOR the new RNN may not need this unrolling, check the input space
        for i in xrange(self.observation_steps):  # Last bucket is the biggest one.
            self.observation_inputs.append(tf.placeholder(tf.float32, shape=[self.batch_size, self.input_size],
                                                          name="observation{0}".format(i)))

        if self.model_type == 'MDN':
            for i in xrange(self.prediction_steps):
                self.future_inputs.append(tf.placeholder(tf.float32, shape=[self.batch_size, self.input_size],
                                                         name="prediction{0}".format(i)))
            for i in xrange(self.prediction_steps):
                self.target_weights.append(tf.placeholder(dtype, shape=[self.batch_size],
                                                        name="weight{0}".format(i)))
            #targets are just the future data
            # Rescale gt data x1 and x2 such that the MDN is judged in smaller unit scale dimensions
            # This is because I do not expect the network to figure out the scaling, and so the Mixture is in unit size scale
            # So the GT must be brought down to meet it.
            targets\
                = [tf.divide(tf.subtract(self.future_inputs[i], scaling_layer[0]), scaling_layer[1])
                   for i in xrange(len(self.future_inputs))]

        #Hook for the input_feed
        self.target_inputs = targets

        #Leave the last observation as the first input to the decoder
        #self.encoder_inputs = self.observation_inputs[0:-1]
        # TODO REFACTOR the new RNN may not need this unrolling, check the input space
        with tf.variable_scope('encoder_inputs'):
            self.encoder_inputs = [_apply_scaling_and_input_layer(input_timestep)
                                   for input_timestep in self.observation_inputs[0:-1]]

        #decoder inputs are the last observation and all but the last future
        with tf.variable_scope('decoder_inputs'):
            self.decoder_inputs = [_apply_scaling_and_input_layer(self.observation_inputs[-1])]

        # Todo should this have the input layer applied?
            self.decoder_inputs.extend([_apply_scaling_and_input_layer(self.future_inputs[i])
                                        for i in xrange(len(self.future_inputs) - 1)])

        #### SEQ2SEQ function HERE

        with tf.variable_scope('seq_rnn'):
            self.MDN_sampled_output, self.losses, self.internal_states, self.MDN_mixture_output =\
                seq2seq_f(self.encoder_inputs, self.decoder_inputs, self.target_inputs, self.observation_inputs[-1])

########### EVALUATOR / LOSS SECTION ###################
        # TODO There are several types of cost functions to compare tracks. Implement many
        # Mainly, average MSE over the whole track, or just at a horizon time (t+10 or something)
        # There's this corner alg that Social LSTM refernces, but I haven't looked into it.
        # NOTE - there is a good cost function for the MDN (MLE), this is different to the track accuracy metric (above)
        if self.model_type == 'MDN':
            self.full_losses = tf.reduce_sum(self.losses) / self.batch_size
            self.first_loss_losses = tf.reduce_sum(self.losses[0])

            self.full_accuracy = -self.full_losses #TODO placeholder, use MSE or something visually intuitive
            self.first_loss_accuracy = -self.first_loss_losses
        if self.model_type == 'classifier':
          raise Exception # This model is MDN only

############# OPTIMIZER SECTION ########################
        # Gradients and SGD update operation for training the model.
        # Here we split the model into training and validation/testing (inference)
        # This allows for slightly different loss functions.
        # The original Alex Graves 2014 paper and the sketch-rnn architectures only do loss on t+1.
        # and they do inference for all time, so I'd like to try that.
        # Because training only occurs in the training section, there is no inference graidents, etc. ONly inference
        # loss and `accuracy'

        tvars = tf.trainable_variables()
        self.first_loss_gradient_norms = []
        self.first_loss_updates = []
        self.full_gradient_norms = []
        self.full_updates = []
        #opt = tf.train.AdadeltaOptimizer(self.learning_rate)
        opt = tf.train.AdamOptimizer(self.learning_rate)
        #opt = tf.train.RMSPropOptimizer(self.learning_rate)
        #opt = tf.train.GradientDescentOptimizer(self.learning_rate)

        first_loss_gradients = tf.gradients(self.first_loss_losses, tvars)
        clipped_first_loss_gradients, first_loss_norm = tf.clip_by_global_norm(first_loss_gradients, self.max_gradient_norm)
        self.first_loss_gradient_norms.append(first_loss_norm)
        first_loss_gradients = zip(clipped_first_loss_gradients, tvars)
        self.first_loss_updates.append(opt.apply_gradients(first_loss_gradients, global_step=self.global_step))

        full_gradients = tf.gradients(self.full_losses, tvars)
        clipped_full_gradients, full_norm = tf.clip_by_global_norm(full_gradients, self.max_gradient_norm)
        self.full_gradient_norms.append(full_norm)
        full_gradients = zip(clipped_full_gradients, tvars)
        self.full_updates.append(opt.apply_gradients(full_gradients, global_step=self.global_step))

############# LOGGING SECTION ###########################
        for gradient, variable in full_gradients:  #plot the gradient of each trainable variable
            if variable.name.find("seq_rnn/combined_tied_rnn_seq2seq/tied_rnn_seq2seq/MultiRNNCell") == 0:
                var_log_name = variable.name[64:] #Make the thing readable in Tensorboard
            else:
                var_log_name = variable.name
            if isinstance(gradient, ops.IndexedSlices):
                grad_values = gradient.values
            else:
                grad_values = gradient
            if not hyper_search:
                self.network_summaries.append(
                    tf.summary.histogram(var_log_name, variable))
                self.network_summaries.append(
                    tf.summary.histogram(var_log_name + "/gradients", grad_values))
                self.network_summaries.append(
                    tf.summary.histogram(var_log_name + "/gradient_norm", clip_ops.global_norm([grad_values])))

        if self.first_loss_only:
            self.network_summaries.append(tf.summary.scalar('Training_Loss', self.first_loss_losses))
        self.network_summaries.append(tf.summary.scalar('Learning_Rate', self.learning_rate))
        self.network_summaries.append(tf.summary.scalar('Loss', self.full_losses))

        self.summary_op = tf.summary.merge(self.network_summaries)

        self.saver = tf.train.Saver(max_to_keep=99999)

        return

    def set_normalization_params(self, session, encoder_means, encoder_stddev):
        # # Function that manually sets the scaling layer for use in input normalization
        session.run(self.scaling_layer[0].assign(encoder_means))
        session.run(self.scaling_layer[1].assign(encoder_stddev))

        return

    """ REFACTORING This is where I need to be specific about input formats, as well as differentiating between the 
    model architecture for training, and the model architecture for generation. Most notably, the generation 
    architecture will need multiple calls to sess.run() as the loopback function will be done manually outside of 
    tensorflow scope. This is done for two reasons, first, I am mimicking previous work done in google's sketch-rnn, so
    I can make some assumptions on generation methods. Second, it allows me to better manipulate the Mixture Density
    Network.
    
    Training is done for the entire length, not just t+1, but the loss is done as a statistical fit. Also, the future 
    decoder feed is always real data, never sampled. 
    
    I need to read up on dynamic rnn. I wonder if I can snapshot the model over multiple sess.run steps, to do the full
    sampling. I doubt it.
    READ https://hanxiao.github.io/2017/08/16/Why-I-use-raw-rnn-Instead-of-dynamic-rnn-in-Tensorflow-So-Should-You-0/
    
    """
    def step(self, session, observation_inputs, future_inputs, target_weights, train_model, summary_writer=None):
        """Run a step of the model feeding the given inputs.
        Args:
          session: tensorflow session to use.
          observation_inputs: list of numpy int vectors to feed as encoder inputs.
          future_inputs: list of numpy float vectors to be used as the future path if doing a path prediction
          target_weights: list of numpy float vectors to feed as target weights.
          train_model: whether to do the backward step or only forward.
        Returns:
          A triple consisting of gradient norm (or None if we did not do backward),
          average perplexity, and the outputs.
        Raises:
          ValueError: if length of encoder_inputs, decoder_inputs, or
            target_weights disagrees with bucket size for the specified bucket_id.
        """

        # Batch Norm Changes
        # The cell should be a drop in replacement above.
        # The tricky part here is that I need to update the state: BN_LSTM.is_training = train_model
        # I should be able to loop over all BN_LSTM Cells in the graph somehow.
        if self.parameters['RNN_cell'] == "BN_LSTMCell":
            for dropout_cell in self._RNN_layers._cells:
                dropout_cell._cell.is_training = train_model

        # Input feed: encoder inputs, decoder inputs, target_weights, as provided.
        input_feed = {}
        for l in xrange(self.observation_steps):
            input_feed[self.observation_inputs[l].name] = observation_inputs[l]
        if self.model_type == 'MDN':
            for l in xrange(self.prediction_steps):
                input_feed[self.future_inputs[l].name] = future_inputs[l]
                input_feed[self.target_weights[l].name] = target_weights[l]
        if self.model_type == 'classifier':
                input_feed[self.target_inputs[0].name] = future_inputs[0]
                input_feed[self.target_weights[0].name] = target_weights[0]

        # Output feed: depends on whether we do a backward step or not.
        if train_model:
            if self.parameters['feed_future_data']:
                print "Error, feed_future_data not implemented. It must be set to false. Exiting..."
                quit()
            if self.first_loss_only:
                output_feed = (self.first_loss_updates +  # Update Op that does SGD. #This is the learning flag
                             self.first_loss_gradient_norms +  # Gradient norm.
                             [self.first_loss_losses] +
                               [self.first_loss_accuracy])  # Loss for this batch.
            else:
                output_feed = (self.full_updates +  # Update Op that does SGD. #This is the learning flag
                               self.full_gradient_norms +  # Gradient norm.
                               [self.full_losses] +
                               [self.full_accuracy])  # Loss for this batch.
        else:
            output_feed = [self.full_accuracy, self.full_losses]  # Loss for this batch.
            if self.model_type == 'MDN':
                output_feed.append(self.MDN_sampled_output)
                output_feed.append(self.MDN_mixture_output)

        outputs = session.run(output_feed, input_feed)
        if summary_writer is not None:

            summary_str = session.run(self.summary_op,input_feed)
            summary_writer.add_summary(summary_str, self.global_step.eval(session=session))
        if train_model:
            return outputs[3], outputs[2], None, None  # accuracy, loss, no outputs.
        else:
            model_sampled_outputs = np.swapaxes(np.array(outputs[2]),0,1).tolist() #Unstack. Ugly formatting for legacy
            return outputs[0], outputs[1],  model_sampled_outputs, outputs[3]  # accuracy, loss, outputs, mixtures

