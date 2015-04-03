# -*-coding: utf-8 -*-
"""
  _   _ _____ _     _____ _____
 | | | |  ___| |   |  ___/  ___|
 | | | | |__ | |   | |__ \ `--.
 | | | |  __|| |   |  __| `--. \
 \ \_/ / |___| |___| |___/\__/ /
  \___/\____/\_____|____/\____/

Created on Mart 21, 2014

Configuration file for Mnist. Model - fully-connected Neural Network with MSE
loss function with target encoded as 7 points.

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


from veles.config import root


# optional parameters
root.mnist7.update({
    "decision": {"fail_iterations": 25, "max_epochs": 1000000},
    "snapshotter": {"prefix": "mnist7"},
    "loader": {"minibatch_size": 60, "force_cpu": False,
               "normalization_type": "linear"},
    "weights_plotter": {"limit": 25},
    "learning_rate": 0.0001,
    "weights_decay": 0.00005,
    "layers": [100, 100, 7]})
