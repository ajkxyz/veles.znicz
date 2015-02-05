"""
Created on Aug 20, 2013

ImageSaver unit.

Copyright (c) 2013 Samsung Electronics Co., Ltd.
"""

from __future__ import division

import logging
import glob
import numpy
import os
import scipy.misc
from zope.interface import implementer

import veles.config as config
from veles.error import BadFormatError
from veles.distributable import IDistributable
from veles.units import Unit, IUnit


@implementer(IUnit, IDistributable)
class ImageSaver(Unit):
    """Saves input to pngs in the supplied directory.

    Will remove all existing png files in the supplied directory.

    Attributes:
        out_dirs: output directories by minibatch_class where to save png.
        input: batch with input samples.
        output: batch with corresponding output samples (may be None).
        target: batch with corresponding target samples (may be None).
        indices: sample indices.
        labels: sample labels.
        max_idx: indices of element with maximum value for each sample.

    Remarks:
        if max_idx is not None:
            Softmax classifier is assumed and only failed samples
            will be saved.
        else:
            MSE task is assumed and output and target
            should be None or not None both simultaneously.
    """
    def __init__(self, workflow, **kwargs):
        super(ImageSaver, self).__init__(workflow, **kwargs)
        self.out_dirs = kwargs.get(
            "out_dirs", [os.path.join(config.root.common.cache_dir,
                                      "tmpimg/test"),
                         os.path.join(config.root.common.cache_dir,
                                      "tmpimg/validation"),
                         os.path.join(config.root.common.cache_dir,
                                      "tmpimg/train")])
        self.limit = kwargs.get("limit", 100)
        self.output = None  # formats.Vector()
        self.target = None  # formats.Vector()
        self.max_idx = None  # formats.Vector()
        self._last_save_time = 0
        self.save_time = 0
        self._n_saved = [0, 0, 0]
        self.demand("color_space", "input", "indices", "labels",
                    "minibatch_class", "minibatch_size")

    @staticmethod
    def as_image(x):
        if len(x.shape) == 1:
            return x.copy()
        elif len(x.shape) == 2:
            return x.reshape(x.shape[0], x.shape[1], 1)
        elif len(x.shape) == 3:
            if x.shape[2] == 3:
                return x
            if x.shape[0] == 3:
                xx = numpy.empty([x.shape[1], x.shape[2], 3],
                                 dtype=x.dtype)
                xx[:, :, 0:1] = x[0:1, :, :].reshape(
                    x.shape[1], x.shape[2], 1)[:, :, 0:1]
                xx[:, :, 1:2] = x[1:2, :, :].reshape(
                    x.shape[1], x.shape[2], 1)[:, :, 0:1]
                xx[:, :, 2:3] = x[2:3, :, :].reshape(
                    x.shape[1], x.shape[2], 1)[:, :, 0:1]
                return xx
            if x.shape[2] == 4:
                xx = numpy.empty([x.shape[0], x.shape[1], 3],
                                 dtype=x.dtype)
                xx[:, :, 0:3] = x[:, :, 0:3]
                return xx
        else:
            raise BadFormatError()

    def initialize(self, **kwargs):
        pass

    def run(self):
        logging.basicConfig(level=logging.INFO)
        if self.output is not None:
            self.output.map_read()
        if self.max_idx is not None:
            self.max_idx.map_read()
        for dirnme in self.out_dirs:
            try:
                os.makedirs(dirnme, mode=0o775)
            except OSError:
                pass
        if self._last_save_time < self.save_time:
            self._last_save_time = self.save_time

            for i in range(len(self._n_saved)):
                self._n_saved[i] = 0
            for dirnme in self.out_dirs:
                files = glob.glob("%s/*.png" % (dirnme))
                for file in files:
                    try:
                        os.unlink(file)
                    except OSError:
                        pass
        if self._n_saved[self.minibatch_class] >= self.limit:
            return
        xyt = None
        x = None
        y = None
        t = None
        im = 0
        for i in range(0, self.minibatch_size):
            x = ImageSaver.as_image(self.input[i])
            idx = self.indices[i]
            lbl = self.labels[i]
            if self.max_idx is not None:
                im = self.max_idx[i]
                if im == lbl:
                    continue
                y = self.output[i]
            if (self.max_idx is None and
                    self.output is not None and self.target is not None):
                y = ImageSaver.as_image(self.output[i])
                t = ImageSaver.as_image(self.target[i])
                y = y.reshape(t.shape)
            if self.max_idx is None and y is not None:
                mse = numpy.linalg.norm(t - y) / x.size
            if xyt is None:
                n_rows = x.shape[0]
                n_cols = x.shape[1]
                if (self.max_idx is None and y is not None and
                        len(y.shape) != 1):
                    n_rows += y.shape[0]
                    n_cols = max(n_cols, y.shape[1])
                if (self.max_idx is None and t is not None and
                        len(t.shape) != 1 and self.input != self.target):
                    n_rows += t.shape[0]
                    n_cols = max(n_cols, t.shape[1])
                xyt = numpy.empty([n_rows, n_cols, x.shape[2]], dtype=x.dtype)
            xyt[:] = 0
            offs = (xyt.shape[1] - x.shape[1]) >> 1
            xyt[:x.shape[0], offs:offs + x.shape[1]] = x[:, :]
            img = xyt[:x.shape[0], offs:offs + x.shape[1]]
            if self.max_idx is None and y is not None and len(y.shape) != 1:
                offs = (xyt.shape[1] - y.shape[1]) >> 1
                xyt[x.shape[0]:x.shape[0] + y.shape[0],
                    offs:offs + y.shape[1]] = y[:, :]
                img = xyt[x.shape[0]:x.shape[0] + y.shape[0],
                          offs:offs + y.shape[1]]
            if (self.max_idx is None and t is not None and
                    len(t.shape) != 1 and self.input != self.target):
                offs = (xyt.shape[1] - t.shape[1]) >> 1
                xyt[x.shape[0] + y.shape[0]:, offs:offs + t.shape[1]] = t[:, :]
                img = xyt[x.shape[0] + y.shape[0]:, offs:offs + t.shape[1]]
            if self.max_idx is None:
                fnme = "%s/%.6f_%d_%d.png" % (
                    self.out_dirs[self.minibatch_class], mse, lbl, idx)
            else:
                fnme = "%s/%d_as_%d.%.0fpt.%d.png" % (
                    self.out_dirs[self.minibatch_class], lbl, im, y[im],
                    idx)
            img = xyt
            if img.shape[2] == 1:
                img = img.reshape(img.shape[0], img.shape[1])
            try:
                scipy.misc.imsave(
                    fnme, self.normalize_image(img, self.color_space))
            except OSError:
                self.warning("Could not save image to %s" % (fnme))

            self._n_saved[self.minibatch_class] += 1
            if self._n_saved[self.minibatch_class] >= self.limit:
                return

    def normalize_image(self, a, colorspace=None):
        """Normalizes numpy array to interval [0, 255].
        """
        aa = a.astype(numpy.float32)
        if aa.__array_interface__[
                "data"][0] == a.__array_interface__["data"][0]:
            aa = aa.copy()
        aa -= aa.min()
        m = aa.max()
        if m:
            m /= 255.0
            aa /= m
        else:
            aa[:] = 127.5
        aa = aa.astype(numpy.uint8)
        if (colorspace != "RGB"):
            import cv2
            aa = cv2.cvtColor(
                aa, getattr(cv2, "COLOR_" + colorspace + "2RGB"))
        return aa

    # IDistributable implementation

    def generate_data_for_slave(self, slave):
        return None

    def generate_data_for_master(self):
        return True

    def apply_data_from_master(self, data):
        pass

    def apply_data_from_slave(self, data, slave):
        pass

    def drop_slave(self, slave):
        pass
