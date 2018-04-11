from scipy.spatial import distance
import numpy as np
from numpy.core.umath_tests import inner1d
import comparative_works
import pandas as pd
import utils_draw_graphs

class ReportWriter:
    def __init__(self,
                 training_batch_handler,
                 validation_batch_handler,
                 test_batch_handler,
                 parameters,
                 report_df):
        """
        training_batch_handler:
        validation_batch_handler:
        test_batch_handler:
            The three data groups to do full hyperparam tuning on a network.
            Other models may need it.
        parameters: The list of all params.
        report_df: the final report generated by the test run. It should only contain d=0 snippets.
        
        """
        report_df.reset_index(inplace=True)
        #print "I CANNOT USE REPORT DF AS IT IS NOT ONLY AT DISTNCE 0"
        #raise ValueError
        #self.write_matlab_csv(report_df)
        compares = comparative_works.comparative_works()

        #class_dist_df = compares.classifierComboDistributionEstimator(training_batch_handler, validation_batch_handler, test_batch_handler, parameters,
        #                              report_df)
        CTRA_df = compares.CTRA_model(training_batch_handler, validation_batch_handler, test_batch_handler, parameters,
                                      report_df)
        CTRV_df = compares.CTRV_model(training_batch_handler, validation_batch_handler, test_batch_handler, parameters,
                                      report_df)
        CV_df = compares.CV_model(training_batch_handler, validation_batch_handler, test_batch_handler, parameters,
                                      report_df)
        #HMM_errors = compares.HMMGMM(training_batch_handler,validation_batch_handler,test_batch_handler,parameters,report_df)
        #VGMM is CATEGORICAL!
        #VGMM_df = compares.VGMM(training_batch_handler, validation_batch_handler, test_batch_handler,
        #                                         parameters, report_df)
        #GP_df = compares.GaussianProcesses(training_batch_handler, validation_batch_handler, test_batch_handler,
        #                                         parameters, report_df)


        dest_errors_dict = {}
        for relative_destination in report_df.relative_destination.unique():
            errors_dict = {}
            #errors_dict['class_dist_df' + '-' + relative_destination] = \
             #   self._score_model_on_metric(class_dist_df[class_dist_df.relative_destination == relative_destination])
            errors_dict['CTRA' + '-' + relative_destination] = \
                self._score_model_on_metric(CTRA_df[CTRA_df.relative_destination == relative_destination])
            errors_dict['CTRV' + '-' + relative_destination] = \
                self._score_model_on_metric(CTRV_df[CTRV_df.relative_destination == relative_destination])
            errors_dict['CV' + '-' + relative_destination] = \
                self._score_model_on_metric(CV_df[CV_df.relative_destination == relative_destination])
            # errors_dict['VGMM'] = self._score_model_on_metric(VGMM_df)
            #errors_dict['GP' + '-' + relative_destination] = \
            #    self._score_model_on_metric(GP_df[GP_df.relative_destination == relative_destination])
            errors_dict['RNN' + '-' + relative_destination] = \
                self._score_model_on_metric(report_df[report_df.relative_destination == relative_destination])
            dest_errors_dict[relative_destination] = errors_dict

        errors_dict = {}
        relative_destination = 'all'
        #errors_dict['class_dist_df' + '-' + relative_destination] = self._score_model_on_metric(class_dist_df)
        errors_dict['CTRA' + '-' + relative_destination] = self._score_model_on_metric(CTRA_df)
        errors_dict['CTRV' + '-' + relative_destination] = self._score_model_on_metric(CTRV_df)
        errors_dict['CV' + '-' + relative_destination] = self._score_model_on_metric(CV_df)
        # errors_dict['VGMM'] = self._score_model_on_metric(VGMM_df)
        #errors_dict['GP' + '-' + relative_destination] = self._score_model_on_metric(GP_df)
        errors_dict['RNN' + '-' + relative_destination] = self._score_model_on_metric(report_df)
        dest_errors_dict['all'] = errors_dict

        # Consolidate everything, grouped by direction
        directionally_consolidated_errors_dict = {}
        for direction, direction_df in dest_errors_dict.iteritems():
            methodically_consolidated_errors_dict = {}
            for name, df in direction_df.iteritems():
                methodically_consolidated_errors_dict[name] = self._consolidate_errors(df)
            directionally_consolidated_errors_dict[direction] = methodically_consolidated_errors_dict
            #consolidated_errors_dict[name]['model'] = name

        # for every other model:
        #   report_df = run_model
        #   model_errors = self._score...()
        # collect all scores and write a CSV or HTML or something.

        ### Here I need to collect all the predictions from every model, shove them in a dict, and run the png plotter
        # I needs to guarantee ordering of the index for aligning prediction tracks.
        assert (CTRA_df.track_idx == report_df.track_idx).all()
        # Also asser that every track is unique
        assert len(report_df) == len(report_df.track_idx.unique())
        for track_idx in report_df.track_idx:
            plt_size = (10, 10)
            utils_draw_graphs.draw_png_heatmap_graph(report_df[report_df.track_idx == track_idx].encoder_sample,
                                                     {"RNN": report_df[report_df.track_idx == track_idx].outputs},
                                                     report_df[report_df.track_idx == track_idx].decoder_sample,  # Ground Truth
                                                     report_df[report_df.track_idx == track_idx].mixtures,
                                                     report_df[report_df.track_idx == track_idx].padding_logits,
                                                     report_df[report_df.track_idx == track_idx].trackwise_padding,
                                                     plt_size,
                                                     False,  # draw_prediction_track,
                                                     "temp",  # self.plot_directory,
                                                     "best",  # self.log_file_name,
                                                     False,  # multi_sample,
                                                     0,  # self.get_global_step(),
                                                     track_idx,  # graph_number,
                                                     "temp",  # fig_dir,
                                                     report_df[report_df.track_idx == track_idx].csv_name.iloc[0],
                                                     parameters)
        # if multithread:
        #     args_dict = {"obs": obs,
        #                  "preds": preds,
        #                  "gt": gt,
        #                  "mixes": mixes,
        #                  "pad_logits": pad_logits,
        #                  "plt_size": self.plt_size,
        #                  "draw_prediction_track": draw_prediction_track,
        #                  "plot_directory": self.plot_directory,
        #                  "log_file_name": self.log_file_name,
        #                  "multi_sample": multi_sample,
        #                  "global_step": self.get_global_step(),
        #                  "graph_number": graph_number,
        #                  "fig_dir": fig_dir,
        #                  "csv_name": csv_name,
        #                  "padding_logits": pad_logits,
        #                  'parameters': self.parameters}
        #     # HACK I would prefer a child that then maintains its own children with queued workers. This allows
        #     # the child process to hand out fresh jobs without interrupting main, but its a lot of work. So instead,
        #     # to stop starving main, I force these to only be able to use half the cores.
        #     p_child = subprocess.Popen(["taskset", "-c", "0,1,2,3",
        #                                 "nice", "-n", "19",
        #                                 "/usr/bin/python2", "utils_draw_graphs.py"], stdin=subprocess.PIPE)
        #     p_child.stdin.write(pickle.dumps(args_dict))
        #     p_child.stdin.close()
        #     self.p_child_list.append(p_child)
        # else:
        #     import utils_draw_graphs
        #     graph_list.append(utils_draw_graphs.draw_png_heatmap_graph(obs, {"RNN": preds}, gt, mixes, pad_logits,
        #                                                                self.plt_size, draw_prediction_track,
        #                                                                self.plot_directory, self.log_file_name,
        #                                                                multi_sample,
        #                                                                self.get_global_step(), graph_number, fig_dir,
        #                                                                csv_name, self.parameters))

        self.errors_df_dict = directionally_consolidated_errors_dict

        return

    def write_matlab_csv(self,report_df):
        for idx, row in report_df.iterrows():

            ideas = None

    def get_results(self):
        return self.errors_df_dict

    def _consolidate_errors(self,error_df):
        metrics = list(error_df.keys())
        summarized_metrics = {}
        for metric in metrics:
            errors = error_df[metric]
            summarized_metrics[metric + " " + 'median'] = np.median(errors)
            summarized_metrics[metric + " " + 'mean'] = np.mean(errors)
            summarized_metrics[metric + " " + 'worst 5%'] = np.percentile(errors, 95)
            summarized_metrics[metric + " " + 'worst 1%'] = np.percentile(errors, 99)
        return summarized_metrics


    # Here, there are many options
    # A) metric variance. LCSS, Hausdorff, etc
    # B) Statistical variance:
        # best mean
        # best worst 5% / 1% / 0.1% <-- It took me ages to get data for a reasonable 0.1% fit!
    def _score_model_on_metric(self, report_df, metric=None):
        #scores_list = []
        track_scores = {}
        horizon_list = [5, 10, 13]#, 25, 38, 50, 63, 75]
        # horizon_dict = {}
        # for dist in horizon_list:
        #     horizon_dict[dist] = []


        for track in report_df.iterrows():

            track = track[1]
            try:
                preds = track.outputs[np.logical_not(track.trackwise_padding)]
            except:
                ideas = None
            gts = track.decoder_sample[np.logical_not(track.trackwise_padding)]

            ### EUCLIDEAN ERROR -- Average
            euclid_error = []
            for pred, gt in zip(preds[:,0:2], gts[:,0:2]):
                # Iterates over each time-step
                euclid_error.append(distance.euclidean(pred, gt))
            ### /EUCLIDEAN

            ### HORIZON METRICS
            for dist in horizon_list:
                if dist >= len(preds):
                    continue
                euclid_error = distance.euclidean(preds[dist, 0:2], gts[dist,0:2])
                #horizon_dict[dist].append(euclid_error)
                try:
                    track_scores["horizon_steps_" + str(dist)].append(euclid_error)
                except KeyError:
                    track_scores["horizon_steps_" + str(dist)] = [euclid_error]

            # Now horizon_dict is keyed by timestep, and contains lists of distance errors
            # Mean, Median, 5% etc can now be done on those arrays.


            ### MODIFIED HAUSDORFF DISTANCE
            # Pulled shamelessly from https://github.com/sapphire008/Python/blob/master/generic/HausdorffDistance.py
            # Thanks sapphire008!
            #TODO Untested. I think it needs to be trackwise, as above
            (A, B) = (preds[:, 0:2], gts[:, 0:2])

            # Find pairwise distance
            # Very occasionally due to rounding errors it D_mat can be a small neg num, resulting in NaN
            D_mat = np.nan_to_num(np.sqrt(inner1d(A, A)[np.newaxis].T +
                            inner1d(B, B) - 2 * (np.dot(A, B.T))))
            # Calculating the forward HD: mean(min(each col))
            try:
                FHD = np.mean(np.min(D_mat, axis=1))
            # Calculating the reverse HD: mean(min(each row))
                RHD = np.mean(np.min(D_mat, axis=0))
                # Calculating mhd
                MHD = np.max(np.array([FHD, RHD]))
            except:
                MHD=999999 # Sometimes the test data doesnt contain any of this particular class.
                        # Should not happen in prod
            ### /MHD

            try:
                track_scores['euclidean'].append(np.mean(np.array(euclid_error)))
                track_scores['MHD'].append(MHD)
            except KeyError:
                track_scores['euclidean'] = [np.mean(np.array(euclid_error))]
                track_scores['MHD'] = [MHD]


            #scores_list.append(track_scores)
        return track_scores

#TODO Make a report_df.pkl for the results, and add a if name is main here to load said cached results.