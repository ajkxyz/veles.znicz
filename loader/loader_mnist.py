# -*-coding: utf-8 -*-
"""
.. invisible:
     _   _ _____ _     _____ _____
    | | | |  ___| |   |  ___/  ___|
    | | | | |__ | |   | |__ \ `--.
    | | | |  __|| |   |  __| `--. \
    \ \_/ / |___| |___| |___/\__/ /
     \___/\____/\_____|____/\____/

Created on Dec 4, 2014

Loads MNIST dataset files.

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


import os
import struct

import numpy
from zope.interface import implementer

from veles.config import root
import veles.error as error
from veles.loader import FullBatchLoader, IFullBatchLoader, TEST, VALID, TRAIN


mnist_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "MNIST"))
if not os.access(mnist_dir, os.W_OK):
    # Fall back to ~/.veles/MNIST
    mnist_dir = os.path.join(root.common.dirs.datasets, "MNIST")
test_image_dir = os.path.join(mnist_dir, "t10k-images.idx3-ubyte")
test_label_dir = os.path.join(mnist_dir, "t10k-labels.idx1-ubyte")
train_image_dir = os.path.join(mnist_dir, "train-images.idx3-ubyte")
train_label_dir = os.path.join(mnist_dir, "train-labels.idx1-ubyte")


@implementer(IFullBatchLoader)
class MnistLoader(FullBatchLoader):
    """Loads MNIST dataset.
    """
    MAPPING = "mnist_loader"

    def load_original(self, offs, labels_count, labels_fnme, images_fnme):
        """Loads data from original MNIST files.
        """
        if not os.path.exists(mnist_dir):
            url = "http://yann.lecun.com/exdb/mnist"
            self.warning("%s does not exist, downloading from %s...",
                         mnist_dir, url)

            import gzip
            import wget

            files = {"train-images-idx3-ubyte.gz": "train-images.idx3-ubyte",
                     "train-labels-idx1-ubyte.gz": "train-labels.idx1-ubyte",
                     "t10k-images-idx3-ubyte.gz": "t10k-images.idx3-ubyte",
                     "t10k-labels-idx1-ubyte.gz": "t10k-labels.idx1-ubyte"}

            os.mkdir(mnist_dir)
            for index, (k, v) in enumerate(sorted(files.items())):
                self.info("%d/%d", index + 1, len(files))
                wget.download("%s/%s" % (url, k), mnist_dir)
                print("")
                with open(os.path.join(mnist_dir, v), "wb") as fout:
                    gz_file = os.path.join(mnist_dir, k)
                    with gzip.GzipFile(gz_file) as fin:
                        fout.write(fin.read())
                    os.remove(gz_file)

        # Reading labels:
        with open(labels_fnme, "rb") as fin:
            header, = struct.unpack(">i", fin.read(4))
            if header != 2049:
                raise error.BadFormatError("Wrong header in train-labels")

            n_labels, = struct.unpack(">i", fin.read(4))
            if n_labels != labels_count:
                raise error.BadFormatError("Wrong number of labels in "
                                           "train-labels")

            arr = numpy.zeros(n_labels, dtype=numpy.byte)
            n = fin.readinto(arr)
            if n != n_labels:
                raise error.BadFormatError("EOF reached while reading labels "
                                           "from train-labels")
            self.original_labels[offs:offs + labels_count] = arr[:]
            if (numpy.min(self.original_labels) != 0 or
                    numpy.max(self.original_labels) != 9):
                raise error.BadFormatError(
                    "Wrong labels range in train-labels.")

        # Reading images:
        with open(images_fnme, "rb") as fin:
            header, = struct.unpack(">i", fin.read(4))
            if header != 2051:
                raise error.BadFormatError("Wrong header in train-images")

            n_images, = struct.unpack(">i", fin.read(4))
            if n_images != n_labels:
                raise error.BadFormatError("Wrong number of images in "
                                           "train-images")

            n_rows, n_cols = struct.unpack(">2i", fin.read(8))
            if n_rows != 28 or n_cols != 28:
                raise error.BadFormatError("Wrong images size in train-images,"
                                           " should be 28*28")

            # 0 - white, 255 - black
            pixels = numpy.zeros(n_images * n_rows * n_cols, dtype=numpy.ubyte)
            n = fin.readinto(pixels)
            if n != n_images * n_rows * n_cols:
                raise error.BadFormatError("EOF reached while reading images "
                                           "from train-images")

        # Transforming images into float arrays and normalizing to [-1, 1]:
        images = pixels.astype(numpy.float32).reshape(n_images, n_rows, n_cols)
        self.original_data.mem[offs:offs + n_images] = images[:]

    def load_data(self):
        """Here we will load MNIST data.
        """
        if not self.testing:
            self.class_lengths[TEST] = 0
            self.class_lengths[VALID] = 10000
            self.class_lengths[TRAIN] = 60000
        else:
            self.class_lengths[TEST] = 70000
            self.class_lengths[VALID] = self.class_lengths[TRAIN] = 0
        self.create_originals((28, 28))
        self.original_labels[:] = (0 for _ in range(len(self.original_labels)))
        self.info("Loading from original MNIST files...")
        self.load_original(0, 10000, test_label_dir, test_image_dir)
        self.load_original(10000, 60000, train_label_dir, train_image_dir)
