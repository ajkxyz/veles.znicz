# -*-coding: utf-8 -*-
"""
.. invisible:
     _   _ _____ _     _____ _____
    | | | |  ___| |   |  ___/  ___|
    | | | | |__ | |   | |__ \ `--.
    | | | |  __|| |   |  __| `--. \
    \ \_/ / |___| |___| |___/\__/ /
     \___/\____/\_____|____/\____/

Created on Nov 20, 2014

Configuration file for AlexNet topology with LMDB loader.

███████████████████████████████████████████████████████████████████████████████

Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.

███████████████████████████████████████████████████████████████████████████████
"""


import numpy
import os

from veles.config import root

base_lr = 0.01
wd = 0.0005

data_path = os.path.join(root.common.datasets_root, "AlexNet/LMDB")

root.common.engine.backend = "cuda"
root.common.precision_type = "float"
root.common.precision_level = 0

root.imagenet.lr_adjuster.lr_parameters = {
    "lrs_with_lengths":
    [(1, 100000), (0.1, 100000), (0.1, 100000), (0.01, 100000000)]}
root.imagenet.lr_adjuster.bias_lr_parameters = {
    "lrs_with_lengths":
    [(1, 100000), (0.1, 100000), (0.1, 100000), (0.01, 100000000)]}


root.imagenet.update({
    "decision": {"fail_iterations": 10000,
                 "max_epochs": 10000000},
    "snapshotter": {"prefix": "imagenet",
                    "directory":
                    os.path.join(root.common.datasets_root,
                                 "AlexNet/snapshots"),
                    "interval": 1, "time_interval": 0},
    "add_plotters": True,
    "image_saver": {"out_dirs":
                    [os.path.join(root.common.datasets_root,
                                  "AlexNet/image_saver/test"),
                     os.path.join(root.common.datasets_root,
                                  "AlexNet/image_saver/validation"),
                     os.path.join(root.common.datasets_root,
                                  "AlexNet/image_saver/train")]},
    "lr_adjuster": {"lr_policy_name": "arbitrary_step",
                    "bias_lr_policy_name": "arbitrary_step"},
    "loss_function": "softmax",
    "loader_name": "lmdb",
    "loader": {"minibatch_size": 256,
               "shuffle_limit": numpy.iinfo(numpy.uint32).max,
               "crop": (227, 227), "mirror": "random",
               "color_space": "RGB", "normalization_type": "external_mean",
               "train_path": os.path.join(data_path, "ilsvrc12_train_lmdb"),
               "validation_path": os.path.join(data_path, "ilsvrc12_val_lmdb"),
               },
    "weights_plotter": {"limit": 256, "split_channels": False},
    "layers": [{"type": "conv_str",
                "->": {"n_kernels": 96, "kx": 11, "ky": 11,
                       "padding": (0, 0, 0, 0), "sliding": (4, 4),
                       "weights_filling": "gaussian", "weights_stddev": 0.01,
                       "bias_filling": "constant", "bias_stddev": 0},
                "<-": {"learning_rate": base_lr,
                       "learning_rate_bias": base_lr * 2,
                       "weights_decay": wd, "weights_decay_bias": 0,
                       "gradient_moment": 0.9, "gradient_moment_bias": 0.9}},
               {"type": "max_pooling",
                "->": {"kx": 3, "ky": 3, "sliding": (2, 2)}},
               {"type": "norm", "n": 5, "alpha": 0.0001, "beta": 0.75},

               {"type": "zero_filter",
                "grouping": 2},
               {"type": "conv_str",
                "->": {"n_kernels": 256, "kx": 5, "ky": 5,
                       "padding": (2, 2, 2, 2), "sliding": (1, 1),
                       "weights_filling": "gaussian", "weights_stddev": 0.01,
                       "bias_filling": "constant", "bias_stddev": 0.1},
                "<-": {"learning_rate": base_lr,
                       "learning_rate_bias": base_lr * 2,
                       "weights_decay": wd, "weights_decay_bias": 0,
                       "gradient_moment": 0.9, "gradient_moment_bias": 0.9}},

               {"type": "norm", "n": 5, "alpha": 0.0001, "beta": 0.75},
               {"type": "max_pooling", "->": {"kx": 3, "ky": 3,
                                              "sliding": (2, 2)}},
               {"type": "conv_str",
                "->": {"n_kernels": 384, "kx": 3, "ky": 3,
                       "padding": (1, 1, 1, 1), "sliding": (1, 1),
                       "weights_filling": "gaussian", "weights_stddev": 0.01,
                       "bias_filling": "constant", "bias_stddev": 0},
                "<-": {"learning_rate": base_lr,
                       "learning_rate_bias": base_lr * 2,
                       "weights_decay": wd, "weights_decay_bias": 0,
                       "gradient_moment": 0.9, "gradient_moment_bias": 0.9}},

               {"type": "zero_filter", "grouping": 2},
               {"type": "conv_str",
                "->": {"n_kernels": 384, "kx": 3, "ky": 3,
                       "padding": (1, 1, 1, 1), "sliding": (1, 1),
                       "weights_filling": "gaussian", "weights_stddev": 0.01,
                       "bias_filling": "constant", "bias_stddev": 0.1},
                "<-": {"learning_rate": base_lr,
                       "learning_rate_bias": base_lr * 2,
                       "weights_decay": wd, "weights_decay_bias": 0,
                       "gradient_moment": 0.9, "gradient_moment_bias": 0.9}},

               {"type": "zero_filter", "grouping": 2},
               {"type": "conv_str",
                "->": {"n_kernels": 256, "kx": 3, "ky": 3,
                       "padding": (1, 1, 1, 1), "sliding": (1, 1),
                       "weights_filling": "gaussian", "weights_stddev": 0.01,
                       "bias_filling": "constant", "bias_stddev": 0.1},
                "<-": {"learning_rate": base_lr,
                       "learning_rate_bias": base_lr * 2,
                       "weights_decay": wd, "weights_decay_bias": 0,
                       "gradient_moment": 0.9, "gradient_moment_bias": 0.9}},
               {"type": "max_pooling",
                "->": {"kx": 3, "ky": 3, "sliding": (2, 2)}},

               {"type": "all2all",
                "->": {"output_sample_shape": 4096,
                       "weights_filling": "gaussian", "weights_stddev": 0.005,
                       "bias_filling": "constant", "bias_stddev": 0.1},
                "<-": {"learning_rate": base_lr,
                       "learning_rate_bias": base_lr * 2,
                       "weights_decay": wd, "weights_decay_bias": 0,
                       "gradient_moment": 0.9, "gradient_moment_bias": 0.9}},
               {"type": "activation_str"},
               {"type": "dropout", "dropout_ratio": 0.5},

               {"type": "all2all",
                "->": {"output_sample_shape": 4096,
                       "weights_filling": "gaussian", "weights_stddev": 0.005,
                       "bias_filling": "constant", "bias_stddev": 0.1},
                "<-": {"learning_rate": base_lr,
                       "learning_rate_bias": base_lr * 2,
                       "weights_decay": wd, "weights_decay_bias": 0,
                       "gradient_moment": 0.9, "gradient_moment_bias": 0.9}},
               {"type": "activation_str"},
               {"type": "dropout", "dropout_ratio": 0.5},

               {"type": "softmax",
                "->": {"output_sample_shape": 1000,
                       "weights_filling": "gaussian", "weights_stddev": 0.01,
                       "bias_filling": "constant", "bias_stddev": 0},
                "<-": {"learning_rate": base_lr,
                       "learning_rate_bias": base_lr * 2,
                       "weights_decay": wd, "weights_decay_bias": 0,
                       "gradient_moment": 0.9, "gradient_moment_bias": 0.9}}]})

root.imagenet.loader.normalization_parameters = {
    "mean_source": os.path.join(root.common.datasets_root,
                                "AlexNet/mean_image_227.JPEG")}
