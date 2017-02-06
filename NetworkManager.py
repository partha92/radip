# Class that handles a single instance of a network.
# Defines the training / testing state,
#  manages tensorboard handles.

# Step function should go here, that means it needs to be passed a BatchHandler,
# so that it can grab data easily
# This should also have the different test types, such as the accuracy graph
# Should it handle the entirety of crossfolding?
# I don't think so, that should go into another class maybe
import matplotlib

matplotlib.use('Agg')

import matplotlib.pyplot as plt
import tensorflow as tf
from seq2seq_model import Seq2SeqModel
import os
import numpy as np
import pandas as pd
from bokeh.plotting import figure, output_file, show, gridplot, save
from bokeh.models.widgets import Button
from bokeh.layouts import widgetbox
from bokeh.layouts import layout

class NetworkManager:
    def __init__(self, parameters, log_file_name=None):
        self.parameters = parameters
        self.network = None
        self.batchHandler = None
        self.sess = None
        self.device = None
        self.log_file_name = log_file_name
        self.model = None
        self.plot_directory = os.path.join(self.parameters['master_dir'],'plots')
        #self.network_name_string = "temp123456" # The unique network name descriptor.
        self.train_chkpt_dir = os.path.join(self.parameters['master_dir'], self.parameters['train_dir'])
        self.summaries_dir = os.path.join(self.parameters['master_dir'],'tensorboard_logs')
        self.train_writer = None
        self.val_writer = None
        self.graph_writer = None

        self.tensorboard_graph_summaries= []
        self.tensorboard_metric_summaries = []

        self.plot_feeds = None
        self.plot_output = None
        self.metric_feeds = None
        self.metric_output = None

        return

    def build_model(self):
        tf.reset_default_graph()
        self.device = tf.device('gpu:0')
        gpu_options = tf.GPUOptions(per_process_gpu_memory_fraction=0.9,allow_growth=True)
        self.sess = tf.Session(config=tf.ConfigProto(allow_soft_placement=True,gpu_options=gpu_options))
        self.model = Seq2SeqModel(self.parameters)
        if not os.path.exists(self.train_chkpt_dir):
            os.makedirs(self.train_chkpt_dir)
        if not os.path.exists(os.path.join(self.train_chkpt_dir, self.log_file_name)):
            os.makedirs(os.path.join(self.train_chkpt_dir, self.log_file_name))
        ckpt = tf.train.get_checkpoint_state(os.path.join(self.train_chkpt_dir, self.log_file_name))
        if ckpt and tf.gfile.Exists(ckpt.model_checkpoint_path):
            print("Reading model parameters from %s" % ckpt.model_checkpoint_path)
            self.model.saver.restore(self.sess, ckpt.model_checkpoint_path)
        else:
            print("Created model with fresh parameters.")
            self.sess.run(tf.initialize_all_variables())

        self.train_writer = tf.train.SummaryWriter(os.path.join(self.summaries_dir,self.log_file_name+'train'),
                                                   graph=self.sess.graph)
        self.val_writer = tf.train.SummaryWriter(os.path.join(self.summaries_dir,self.log_file_name+'val'),
                                                 graph=self.sess.graph)
        self.build_image_logger()
        self.build_metric_logger()

        return

    def build_image_logger(self):
        plot_feeds = []
        outputs = []
        with tf.variable_scope('result_plots'):
            for label_num in range(self.parameters['num_classes']):
                plot_feed = tf.placeholder(tf.uint8,name=str(label_num))
                self.tensorboard_graph_summaries.append(tf.image_summary(plot_feed.name,plot_feed,max_images=1))
                max = tf.arg_max(plot_feed,0)
                plot_feeds.append(plot_feed)
                outputs.append(max)
        if self.graph_writer is None:
            self.graph_writer = tf.train.SummaryWriter(os.path.join(self.summaries_dir,self.log_file_name+'graph'),
                                                 graph=self.sess.graph)
        self.plot_feeds = plot_feeds
        self.plot_output = outputs
        return

    def log_graphs_to_tensorboard(self,graphs):
        summary_op = tf.merge_summary(self.tensorboard_graph_summaries)

        input_feed = {}
        output_feed = []
        for i in range(len(self.plot_feeds)):
            input_feed[self.plot_feeds[i].name] = [graphs[i]] #Wrapped to be a batch size of 1
            output_feed.append([self.plot_output[i].name])  # Wrapped to be a batch size of 1

        junk = self.sess.run(output_feed,input_feed)
        summary_str = self.sess.run(summary_op,input_feed)
        self.graph_writer.add_summary(summary_str, self.model.global_step.eval(session=self.sess))
        return

    def build_metric_logger(self):
        metric_feeds = []
        outputs = []
        with tf.variable_scope('metric_scalars'):
            for label_num in range(self.parameters['num_classes']):
                metric_feed = tf.placeholder(tf.float32, name="class"+str(label_num))
                self.tensorboard_metric_summaries.append(tf.scalar_summary(metric_feed.name, metric_feed))
                #max = tf.arg_max(metric_feed, 0)
                metric_feeds.append(metric_feed)
                outputs.append(metric_feed)
        if self.graph_writer is None:
            self.graph_writer = tf.train.SummaryWriter(os.path.join(self.summaries_dir, self.log_file_name + 'graph'),
                                                   graph=self.sess.graph)
        self.metric_feeds = metric_feeds
        self.metric_output = outputs
        return

    def log_metric_to_tensorboard(self,metrics):
        summary_op = tf.merge_summary(self.tensorboard_metric_summaries)

        input_feed = {}
        output_feed = []
        for i in range(len(self.metric_feeds)):
            input_feed[self.metric_feeds[i].name] = metrics[i]  # Wrapped to be a batch size of 1
            output_feed.append([self.metric_output[i].name])  # Wrapped to be a batch size of 1

        junk = self.sess.run(output_feed, input_feed)
        summary_str = self.sess.run(summary_op, input_feed)
        self.graph_writer.add_summary(summary_str, self.model.global_step.eval(session=self.sess))
        return

    def get_global_step(self):
        return self.model.global_step.eval(session=self.sess)

    def get_learning_rate(self):
        return self.model.learning_rate.eval(session=self.sess)

    def run_training_step(self, X, Y, weights, train_model, summary_writer=None):
         return self.model.step(self.sess, X, Y, weights, train_model, summary_writer=summary_writer)

    def draw_html_graphs(self, graph_results):
        if True:  # Plot HTML bokeh
            plot_titles = graph_results['destination'].unique()
            plots = []
            if not os.path.exists(self.plot_directory):
                os.makedirs(self.plot_directory)
            plt_path = os.path.join(self.plot_directory, self.log_file_name + '.html')
            output_file(plt_path)
            for origin in plot_titles:

                if os.path.exists("QDA/" + origin + ".npy"):
                    QDA_data = np.load("QDA/" + origin + ".npy")
                QDA_mean = QDA_data[0] / 100
                QDA_meanpstd = QDA_data[1] / 100
                QDA_meanmstd = QDA_data[2] / 100
                QDA_range = np.array(range(len(QDA_mean)))
                QDA_range -= 40

                plt_title = 'Accuracy as measured relative to 20m mark. Averaged over all tracks'
                # plot 1
                dataset = graph_results[graph_results['origin'] == origin]
                x_data = []
                y_data = []
                for range_val in np.unique(dataset['d_thresh']):
                    # If I group by track number here, I can get a collection of accuracy scores
                    # and therefore a std dev
                    data_at_range = dataset[dataset['d_thresh'] == range_val]
                    acc = np.average(np.equal(data_at_range['output_idxs'],
                                              data_at_range['destination_vec']))
                    x_data.append(range_val)
                    y_data.append(acc)

                p1 = figure(title='Origin: ' + origin, x_axis_label='Dis from Ref Line (m)', y_axis_label='Acc.',
                            plot_width=400, plot_height=400)  # ~half a 1080p screen
                p1.line(x_data, y_data, legend="Acc. RNN", line_width=2, color='green')
                p1.line(QDA_range, QDA_mean, legend="Acc. QDA", line_width=2, color='red', line_alpha=1)
                # p1.line(QDA_range, QDA_meanmstd, line_width=2, color='red', line_alpha=0.5)
                # p1.line(QDA_range, QDA_meanpstd, line_width=2, color='red', line_alpha=0.5)
                # p1.line(bbox_range, loss, legend="Loss.", line_width=2, color='blue')
                # p1.line(bbox_range, output_gen_plt[:, 1], legend="Generated Output.", line_width=2, color='red')
                p1.legend.location = "bottom_right"
                plots.append(p1)

            button_1 = Button(label=str(self.parameters))

            # put the results in a row

            # p1 = figure(title='Log: ' + get_log_filename(),plot_width=400, plot_height=40)
            # p1.line(1, 1, line_width=2, color='green')
            # plots.append(p1)
            p = gridplot([plots])
            l = layout([plots, [widgetbox(button_1, width=300)]])
            save(l)
            # show(widgetbox(button_1, width=300))

        return

    def draw_png_graphs(self, graph_results):
        fig_dir = self.plot_directory + "_img"
        if not os.path.exists(fig_dir):
            os.makedirs(fig_dir)

        graph_list = []

        plot_titles = graph_results['destination'].unique()
        for origin in plot_titles:
            if os.path.exists("QDA/" + origin + ".npy"):
                QDA_data = np.load("QDA/" + origin + ".npy")
            QDA_mean = QDA_data[0] / 100
            QDA_meanpstd = QDA_data[1] / 100
            QDA_meanmstd = QDA_data[2] / 100
            QDA_range = np.array(range(len(QDA_mean)))
            QDA_range -= 40
            dataset = graph_results[graph_results['origin'] == origin]
            x_data = []
            y_data = []
            for range_val in np.unique(dataset['d_thresh']):
                # If I group by track number here, I can get a collection of accuracy scores
                # and therefore a std dev
                data_at_range = dataset[dataset['d_thresh'] == range_val]
                acc = np.average(np.equal(data_at_range['output_idxs'],
                                          data_at_range['destination_vec']))
                x_data.append(range_val)
                y_data.append(acc)

            legend_str = []
            fig = plt.figure(figsize=(10, 10))
            plt.plot(x_data, y_data,'g-',label=origin)
            legend_str.append(['Acc. RNN'])
            plt.plot(QDA_range, QDA_mean,'r-')
            legend_str.append(['Acc. QDA'])
            plt.legend(legend_str, loc='upper left')
            plt.title('Origin: ' + origin)
            plt.xlabel('Distance from Ref Line (m)')
            plt.ylabel('Accuracy')

            fig_path = os.path.join(self.plot_directory + "_img", self.log_file_name + '-' +
                                    str(self.get_global_step()) + '-' + origin+ '.png')
            plt.savefig(fig_path, bbox_inches='tight')

            fig.canvas.draw()
            fig_s = fig.canvas.tostring_rgb()
            fig_data = np.fromstring(fig_s,np.uint8)
            fig_data = fig_data.reshape(fig.canvas.get_width_height()[::-1] + (3,))
            graph_list.append(fig_data)
            plt.close()

        return graph_list

    # This function needs the validation batch (or test batch)
    def compute_result_per_dis(self, batch_handler, plot=True):
        if plot:
            bbox_range_plot = np.arange(-35,60,1).tolist()
        else:
            bbox_range_plot = np.arange(-35, 60, 0.5).tolist()

        graph_results = []
        # This could be optimized.
        # If the batch size is larger than twice a sequential minibatch
        # I could run two distances per step.
        for d in bbox_range_plot:
            # Set d_thresh
            # Do it in a loop in case batch_size < num_val_tracks
            batch_handler.set_distance_threshold(d)
            batch_complete = False
            while not batch_complete:

                        mini_batch_frame,batch_complete = batch_handler.get_sequential_minibatch()
                        val_x, _, val_weights, val_y = \
                            batch_handler.format_minibatch_data(mini_batch_frame['encoder_sample'],
                                                                mini_batch_frame['dest_1_hot'],
                                                                mini_batch_frame['padding'])
                        valid_data = np.logical_not(mini_batch_frame['padding'].values)
                        acc, loss, outputs = self.model.step(self.sess, val_x, val_y,
                                                             val_weights, False, summary_writer=None)
                        output_idxs = np.argmax(outputs[0][valid_data], axis=1)

                        mini_batch_frame = mini_batch_frame[mini_batch_frame['padding'] == False]
                        mini_batch_frame = mini_batch_frame.assign(output_idxs=output_idxs)
                        mini_batch_frame = mini_batch_frame.assign(d_thresh=np.repeat(d,len(mini_batch_frame)))

                        graph_results.append(mini_batch_frame)

        #Concat once only, much faster
        graph_results_frame = pd.concat(graph_results)

        # Reset handler
        batch_handler.set_distance_threshold(None)

        return graph_results_frame

    def evaluate_metric(self,results):

        d_array = []
        for origin in results['origin'].unique():
            # Generate the set of all distances that are not 100% accurate (i.e. they have a incorrect classification)
            # Remove from the set of all distances, creating only a set of distances with a perfect score
            # Return lowest number (the earliest result)
            dis_unique = results['d_thresh'].unique()
            dist_delta = dis_unique[1] - dis_unique[0]
            reduced_df = results[results['origin']==origin]
            perfect_dist = np.setdiff1d(dis_unique,
                                        reduced_df[
                                            reduced_df['destination_vec']!=reduced_df['output_idxs']
                                        ].d_thresh.unique())
            #If we got none right OR the final value is incorrect (rare case)
            if (len(perfect_dist) == 0) or\
                    (perfect_dist[-1] != dis_unique[-1]):
                d_array.append(np.max(dis_unique))
            else:
                # Find the end of the continuous sequence at the end of the graph
                # Return this point
                for i in reversed(range(1,len(perfect_dist))):
                    if perfect_dist[i] - perfect_dist[i-1] != dist_delta:
                        break
                perfect_dist_threshold = perfect_dist[i]
                d_array.append(np.min(perfect_dist_threshold))

        return d_array

    # Function that passes the entire validation dataset through the network once and only once.
    # Return cumulative accuracy, loss
    def run_validation(self, batch_handler, summary_writer=None,quick=False):
        batch_complete = False
        batch_losses = []
        total_correct = 0
        total_valid = 0
        while not batch_complete:

            #val_x, val_y, val_weights, pad_vector, batch_complete = batch_handler.get_sequential_minibatch()
            if 'QUICK_VALBATCH' in os.environ or quick:
                # Run one regular batch. Debug mode takes longer, and there are ~30,000 val samples
                mini_batch_frame = batch_handler.get_minibatch()
                batch_complete = True
                #print "Debug active, valdating with random sample, not whole batch"
            else:
                mini_batch_frame,batch_complete = batch_handler.get_sequential_minibatch()

            val_x, _, val_weights, val_y = batch_handler.format_minibatch_data(mini_batch_frame['encoder_sample'],
                                                                               mini_batch_frame['dest_1_hot'],
                                                                               mini_batch_frame['padding'])
            valid_data = np.logical_not(mini_batch_frame['padding'].values)
            acc, loss, outputs = self.model.step(self.sess, val_x, val_y, val_weights, False, summary_writer=summary_writer)

            output_idxs = np.argmax(outputs[0][valid_data], axis=1)
            y_idxs = np.argmax(np.array(val_y)[0][valid_data], axis=1)
            num_correct = np.sum(np.equal(output_idxs,y_idxs)*1)
            num_valid = np.sum(valid_data*1)
            total_correct += num_correct
            total_valid += num_valid
            batch_losses.append(loss)

        batch_acc = np.float32(total_correct) / np.float32(total_valid)

        return batch_acc, np.average(batch_losses), None

