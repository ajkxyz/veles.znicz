#!/usr/bin/python3 -O
"""
Created on April 3, 2014

Copyright (c) 2013 Samsung Electronics Co., Ltd.
"""


import numpy
import os

from veles.config import root
import veles.prng as prng
from veles.snapshotter import Snapshotter
from veles.tests import timeout, multi_device
from veles.znicz.tests.functional import StandardTest
import veles.znicz.tests.research.VideoAE.video_ae as video_ae


class TestVideoAE(StandardTest):
    @classmethod
    def setUpClass(cls):
        prng.get(2).seed(numpy.fromfile("%s/veles/znicz/tests/research/seed2" %
                                        root.common.veles_dir,
                                        dtype=numpy.uint32, count=1024))
        root.video_ae.update({
            "snapshotter": {"prefix": "video_ae_test"},
            "decision": {"fail_iterations": 100},
            "loader": {
                "minibatch_size": 50, "force_cpu": False,
                "train_paths": (os.path.join(root.common.test_dataset_root,
                                "video_ae/img"),),
                "color_space": "GRAY",
                "background_color": (0x80,),
                "normalization_type": "mean_disp"},
            "weights_plotter": {"limit": 16},
            "learning_rate": 0.01,
            "weights_decay": 0.00005,
            "layers": [9, [90, 160]]})

    @timeout(1800)
    @multi_device()
    def test_video_ae(self):
        self.info("Will test video_ae workflow")

        self.w = video_ae.VideoAEWorkflow(self.parent,
                                          layers=root.video_ae.layers)
        self.w.decision.max_epochs = 4
        self.w.snapshotter.time_interval = 0
        self.w.snapshotter.interval = 4
        self.w.initialize(device=self.device,
                          learning_rate=root.video_ae.learning_rate,
                          weights_decay=root.video_ae.weights_decay,
                          snapshot=False)
        self.w.run()
        file_name = self.w.snapshotter.file_name

        avg_mse = self.w.decision.epoch_metrics[2][0]
        self.assertLess(avg_mse, 0.1957178)
        self.assertEqual(4, self.w.loader.epoch_number)

        self.info("Will load workflow from %s", file_name)
        self.wf = Snapshotter.import_(file_name)
        self.assertTrue(self.wf.decision.epoch_ended)
        self.wf.decision.max_epochs = 7
        self.wf.decision.complete <<= False
        self.wf.initialize(device=self.device,
                           learning_rate=root.video_ae.learning_rate,
                           weights_decay=root.video_ae.weights_decay,
                           snapshot=True)
        self.wf.run()

        avg_mse = self.wf.decision.epoch_metrics[2][0]
        self.assertLess(avg_mse, 0.18736321)
        self.assertEqual(7, self.wf.loader.epoch_number)
        self.info("All Ok")


if __name__ == "__main__":
    StandardTest.main()
