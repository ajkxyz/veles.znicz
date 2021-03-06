# -*- coding: utf-8 -*-
"""
.. invisible:
     _   _ _____ _     _____ _____
    | | | |  ___| |   |  ___/  ___|
    | | | | |__ | |   | |__ \ `--.
    | | | |  __|| |   |  __| `--. \
    \ \_/ / |___| |___| |___/\__/ /
     \___/\____/\_____|____/\____/

Created on Jan 28, 2014

Base Forward and Backward Units for Neural Networks

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


from __future__ import division
from collections import defaultdict
import gc
import numpy
import logging
import time
import six
import tarfile
from zope.interface import implementer
from veles.avatar import Avatar

from veles.external.prettytable import PrettyTable
from veles.distributable import IDistributable
from veles.loader import Loader
from veles.memory import reshape_transposed, roundup, Array
from veles.mutable import Bool
from veles.accelerated_units import AcceleratedUnit, AcceleratedWorkflow
import veles.prng as prng
from veles.units import UnitCommandLineArgumentsRegistry
from veles.workflow import Repeater
from veles.snapshotter import SnapshotterBase, SnapshotterToFile, \
    SnapshotterToDB
from veles.timeit2 import timeit
from veles.znicz.decision import DecisionBase
from veles.znicz.evaluator import EvaluatorBase


class Match(list):
    @property
    def forward(self):
        for item in self:
            if issubclass(item, ForwardBase):
                return item
        raise IndexError()

    @property
    def has_forward(self):
        for item in self:
            if issubclass(item, ForwardBase):
                return True
        return False

    @property
    def backwards(self):
        for item in self:
            if not issubclass(item, ForwardBase):
                yield item


class MatchingObject(UnitCommandLineArgumentsRegistry):
    mapping = defaultdict(Match)
    logger = logging.getLogger("Matcher")

    def __init__(cls, name, bases, clsdict):
        super(MatchingObject, cls).__init__(name, bases, clsdict)
        if not MatchingObject.enabled:
            return
        mapping = clsdict.get('MAPPING', None)
        if mapping is None:
            MatchingObject.logger.warning("%s does not have MAPPING", cls)
            return
        if not isinstance(mapping, set):
            raise TypeError("%s: MAPPING must be of type 'set'" % cls)
        for val in mapping:
            match = MatchingObject.mapping[val]
            if issubclass(cls, Forward) and match.has_forward and \
                    cls != match.forward:
                raise ValueError(
                    "%s: attempted to add a second Forward %s to %s" %
                    (val, cls, match.forward))
            match.append(cls)


@six.add_metaclass(MatchingObject)
class ForwardBase(AcceleratedUnit):
    """Base class for forward propagation units.
    """
    hide_from_registry = True
    MAPPING = set()


@implementer(IDistributable)
class Forward(ForwardBase):
    """Class for forward propagation units.

    Attributes:
        input: input layer values.
        output: output layer values.
        weights: weights.
        bias: bias.
        weights_stddev: magnitude of the random distribution for weights.
        bias_stddev: magnitude of the random distribution for bias.
        rand: prng.Rand() object for initial weights generation.
    """
    hide_from_registry = True
    MAPPING = set()

    def __init__(self, workflow, **kwargs):
        kwargs["view_group"] = kwargs.get("view_group", "WORKER")
        super(Forward, self).__init__(workflow, **kwargs)
        self.weights_stddev = kwargs.get("weights_stddev")
        self.bias_stddev = kwargs.get("bias_stddev", self.weights_stddev)
        self.weights_filling = kwargs.get("weights_filling", "uniform")
        self.bias_filling = kwargs.get("bias_filling", "uniform")
        self.rand = kwargs.get("rand", prng.get())
        self.weights_transposed = kwargs.get("weights_transposed", False)
        self.include_bias = kwargs.get("include_bias", True)
        self.demand("input")
        self.output = Array(shallow_pickle=True)
        self.weights = Array()
        self.bias = Array()
        self.forward_mode = False
        self.exports = ["weights", "bias", "include_bias",
                        "weights_transposed"]

    @property
    def forward_mode(self):
        return self._forward_mode

    @forward_mode.setter
    def forward_mode(self, value):
        if not isinstance(value, bool):
            raise TypeError(
                "forward_mode must be boolean (got %s)" % type(value))
        self._forward_mode = value

    def initialize(self, device, **kwargs):
        self.forward_mode = kwargs.get("forward_mode", False)
        super(Forward, self).initialize(device=device, **kwargs)

    def generate_data_for_slave(self, slave):
        if self.forward_mode:
            return None
        data = [None, None]
        if self.weights:
            self.weights.map_read()
            data[0] = self.weights.mem
        if self.bias:
            self.bias.map_read()
            data[1] = self.bias.mem
        return data

    def generate_data_for_master(self):
        return None

    def apply_data_from_master(self, data):
        if self.forward_mode:
            return
        if self.weights:
            self.weights.map_invalidate()
            numpy.copyto(self.weights.mem, data[0])
        else:
            self.weights.reset(data[0])
        if self.bias:
            self.bias.map_invalidate()
            numpy.copyto(self.bias.mem, data[1])
        else:
            self.bias.reset(data[1])

    def apply_data_from_slave(self, data, slave):
        pass

    def drop_slave(self, slave):
        pass


class NNLayerBase(Forward):
    MAPPING = set()

    def print_debug_data(self, t_start):
        """Show some statistics.
        """
        if not self.logger.isEnabledFor(logging.DEBUG):
            return
        self.output.map_read()
        y = self.output.mem
        if y.dtype in (numpy.complex64, numpy.complex128):
            self.debug(
                "%s: %d samples with %d weights in %.2f sec: "
                "y: min avg max: %.6f %.6f %.6f" %
                (self.__class__.__name__, y.shape[0],
                 self.weights.mem.size, time.time() - t_start,
                 min(y.real.min(), y.imag.min()),
                 (numpy.average(y.real) + numpy.average(y.imag)) * 0.5,
                 max(y.real.max(), y.imag.max())))
        else:
            self.debug(
                "%s: %d samples with %d weights in %.2f sec: "
                "y: min avg max: %.6f %.6f %.6f" %
                (self.__class__.__name__, y.shape[0],
                 self.weights.mem.size, time.time() - t_start,
                 y.min(), numpy.average(y), y.max()))

    def ocl_run(self):
        """Forward propagation from batch on GPU.
        """
        self.unmap_vectors(self.output, self.input, self.weights, self.bias)
        self.execute_kernel(self._global_size, self._local_size)


class GradientDescentWithActivation(AcceleratedUnit):
    hide_from_registry = True

    def __init__(self, workflow, **kwargs):
        super(GradientDescentWithActivation, self).__init__(workflow, **kwargs)
        self.krn_err_output_name = None
        self.demand("output")

    def initialize(self, device, **kwargs):
        assert (type(self.krn_err_output_name) == str and
                len(self.krn_err_output_name))
        assert self.err_output.shape == self.output.shape
        super(GradientDescentWithActivation, self).initialize(device, **kwargs)
        self.output.initialize(device)

    def ocl_init(self):
        super(GradientDescentWithActivation, self).ocl_init()
        self.krn_err_output_ = self.get_kernel(self.krn_err_output_name)
        self.krn_err_output_.set_args(self.err_output.devmem,
                                      self.output.devmem)
        self._global_size_err_output = (self.err_output.size,)
        self._local_size_err_output = None

    def cuda_init(self):
        super(GradientDescentWithActivation, self).cuda_init()
        self.krn_err_output_ = self.get_kernel(self.krn_err_output_name)
        self.krn_err_output_.set_args(self.err_output.devmem,
                                      self.output.devmem)
        block_size = self.device.suggest_block_size(self.krn_err_output_)
        self._global_size_err_output = (int(numpy.ceil(
            self.err_output.size / block_size)), 1, 1)
        self._local_size_err_output = (block_size, 1, 1)


@implementer(IDistributable)
@six.add_metaclass(MatchingObject)
class GradientDescentBase(AcceleratedUnit):
    """Base class for gradient descent units.

    Attributes:
        input: input layer values.
        output: output layer values.
        err_output: error to backpropagate.
        err_input: backpropagated error.
        weights: weights.
        bias: bias.
        batch_size: current minibatch size.
        learning_rate: gradient descent speed (positive).
        learning_rate_bias
        weights_decay: regularization for weights (see l1_vs_l2).
        weights_decay_bias
        gradient_moment: moment coefficient for weights.
        gradient_moment_bias
        gradient_weights_with_moment: accumulated moment.
        gradient_bias_with_moment
        batch_size: effective batch size (if None, get it from y).
        weights_transposed: assume weights matrix as a transposed one.
        apply_gradient: will apply gradient.
        gradient_changed: when True, slave will send gradients to master
            (assigned to True just before the run call, so it can be set to
            False inside ocl_run, numpy_run if necessary).
        ocl_set_const_args: True when constant arguments for the kernel
                            had been changed and need to be set again.
    """
    hide_from_registry = True
    MAPPING = set()

    REDUCE_SIZE = 64  # used for updating bias

    OP_NONE = 0
    OP_STORE = 1
    OP_ADD = 2
    OP_FLUSH = 3

    def __init__(self, workflow, **kwargs):
        kwargs["view_group"] = kwargs.get("view_group", "TRAINER")
        super(GradientDescentBase, self).__init__(workflow, **kwargs)
        self.err_input = Array(shallow_pickle=True)
        self.ocl_set_const_args = True
        self.weights = None
        self.bias = None
        self.demand("input", "err_output")
        self.learning_rate = kwargs.get("learning_rate", 0.01)
        self.learning_rate_bias = kwargs.get("learning_rate_bias",
                                             self.learning_rate)
        self.weights_decay = kwargs.get("weights_decay", 0.00005)
        self.weights_decay_bias = kwargs.get("weights_decay_bias", 0.0)
        self.l1_vs_l2 = kwargs.get("l1_vs_l2", 0)
        self.l1_vs_l2_bias = kwargs.get("l1_vs_l2_bias", self.l1_vs_l2)
        self.gradient_moment = kwargs.get("gradient_moment", 0)
        self.gradient_moment_bias = kwargs.get("gradient_moment_bias",
                                               self.gradient_moment)
        self.weights_transposed = kwargs.get("weights_transposed", False)
        self.need_err_input = kwargs.get("need_err_input", True)
        self.include_bias = kwargs.get("include_bias", True)
        self.factor_ortho = kwargs.get("factor_ortho", 0)
        self.col_sums = Array()  # for orthogonalization

        # Current gradient as it is without applying learning_rate etc.
        self.gradient_weights = Array()
        self.gradient_bias = Array()

        # Gradient with applied learning_rate etc.
        # optionally accumulated from the previous run
        self.accumulated_gradient_weights = Array()
        self.accumulated_gradient_bias = Array()

        # Gradient with accumulated moments
        self.gradient_weights_with_moment = Array()
        self.gradient_bias_with_moment = Array()

        # Sets to True when gradient changes
        self.gradient_changed = False

        # Gradient will be applied to weights immediately just after computing
        self.apply_gradient = kwargs.get("apply_gradient",
                                         not workflow.is_slave)

        # Accumulates gradient from the previous run:
        # OP_NONE: do not allocate array at all
        # OP_STORE: stores gradient with an applied learning_rate etc.
        # OP_ADD: adds current gradient to the array
        # OP_FLUSH: applies accumulated gradient, then resets it to zero
        self.accumulate_gradient = kwargs.get("accumulate_gradient",
                                              self.OP_NONE)

    @property
    def current_batch_size(self):
        batch_size = getattr(self, "batch_size", None)
        if batch_size is None:
            return self.err_output.mem.shape[0]
        return int(batch_size)

    def initialize(self, device, **kwargs):
        super(GradientDescentBase, self).initialize(device, **kwargs)

        if self.weights:
            assert len(self.weights.shape) == 2
            self.weights_shape = (tuple(reversed(self.weights.shape))
                                  if self.weights_transposed
                                  else self.weights.shape)
        else:
            self.weights_shape = None

        self.learning_rate = kwargs.get("learning_rate", self.learning_rate)
        self.weights_decay = kwargs.get("weights_decay", self.weights_decay)
        self.gradient_moment = kwargs.get("gradient_moment",
                                          self.gradient_moment)
        self.learning_rate_bias = kwargs.get("learning_rate_bias",
                                             self.learning_rate_bias)
        self.weights_decay_bias = kwargs.get("weights_decay_bias",
                                             self.weights_decay_bias)
        self.gradient_moment_bias = kwargs.get("gradient_moment_bias",
                                               self.gradient_moment_bias)

        if self.weights:
            if not self.gradient_weights:
                self.gradient_weights.reset(numpy.zeros_like(self.weights.mem))
            else:
                assert self.gradient_weights.size == self.weights.size

        if self.weights and self.accumulate_gradient != self.OP_NONE:
            if not self.accumulated_gradient_weights:
                self.accumulated_gradient_weights.reset(
                    numpy.zeros_like(self.weights.mem))
            else:
                assert (self.accumulated_gradient_weights.size ==
                        self.weights.size)

        if self.weights and (self.gradient_moment or not self.is_standalone):
            if not self.gradient_weights_with_moment:
                self.gradient_weights_with_moment.reset(
                    numpy.zeros_like(self.weights.mem))
            else:
                assert self.gradient_weights_with_moment.size == \
                    self.weights.size

        if (self.include_bias and self.bias and
            (not self.gradient_bias or
             self.gradient_bias.size != self.bias.size)):
            self.gradient_bias.reset(numpy.zeros_like(self.bias.mem))

        if (self.include_bias and self.bias and
            self.accumulate_gradient != self.OP_NONE and
            (not self.accumulated_gradient_bias or
             self.accumulated_gradient_bias.size != self.bias.size)):
            self.accumulated_gradient_bias.reset(numpy.zeros_like(
                self.bias.mem))

        if (self.include_bias and self.bias and
                (self.gradient_moment_bias or not self.is_standalone)):
            if not self.gradient_bias_with_moment:
                self.gradient_bias_with_moment.reset(
                    numpy.zeros_like(self.bias.mem))
            else:
                assert self.gradient_bias_with_moment.size == self.bias.size

        dtype = self.err_output.dtype
        if self.need_err_input:
            if not self.err_input:
                self.err_input.reset(numpy.zeros(self.input.shape, dtype))
            else:
                assert self.err_input.shape == self.input.shape

        if self.weights:
            side = self.weights_shape[0]
            other = self.weights.size // side
            if self.factor_ortho:
                if not self.col_sums:
                    self.col_sums.reset(numpy.zeros(other, dtype=dtype))
                else:
                    assert self.col_sums.size == other
                self.col_sums.initialize(self.device)
            self.reduce_size = roundup(min(self.reduce_size, other), 32)
            self.weights.initialize(self.device)

        for vec in self.bias, self.input, self.err_input:
            if vec:
                vec.initialize(self.device)
        self.init_vectors(
            self.err_output,
            self.gradient_weights, self.gradient_bias,
            self.accumulated_gradient_weights, self.accumulated_gradient_bias,
            self.gradient_weights_with_moment, self.gradient_bias_with_moment)

    @property
    def learning_rate(self):
        return self._learning_rate

    @learning_rate.setter
    def learning_rate(self, value):
        self._learning_rate = value
        self.ocl_set_const_args = True

    @property
    def weights_decay(self):
        return self._weights_decay

    @weights_decay.setter
    def weights_decay(self, value):
        self._weights_decay = value
        self.ocl_set_const_args = True

    @property
    def l1_vs_l2(self):
        return self._l1_vs_l2

    @l1_vs_l2.setter
    def l1_vs_l2(self, value):
        self._l1_vs_l2 = value
        self.ocl_set_const_args = True

    @property
    def gradient_moment(self):
        return self._gradient_moment

    @gradient_moment.setter
    def gradient_moment(self, value):
        self._gradient_moment = value
        self.ocl_set_const_args = True

    @property
    def learning_rate_bias(self):
        return self._learning_rate_bias

    @learning_rate_bias.setter
    def learning_rate_bias(self, value):
        self._learning_rate_bias = value
        self.ocl_set_const_args = True

    @property
    def weights_decay_bias(self):
        return self._weights_decay_bias

    @weights_decay_bias.setter
    def weights_decay_bias(self, value):
        self._weights_decay_bias = value
        self.ocl_set_const_args = True

    @property
    def l1_vs_l2_bias(self):
        return self._l1_vs_l2_bias

    @l1_vs_l2_bias.setter
    def l1_vs_l2_bias(self, value):
        self._l1_vs_l2_bias = value
        self.ocl_set_const_args = True

    @property
    def gradient_moment_bias(self):
        return self._gradient_moment_bias

    @gradient_moment_bias.setter
    def gradient_moment_bias(self, value):
        self._gradient_moment_bias = value
        self.ocl_set_const_args = True

    def gpu_weights_update(self):
        self.unmap_vectors(
            self.input, self.err_output, self.weights,
            self.gradient_weights, self.accumulated_gradient_weights,
            self.gradient_weights_with_moment)

        if self.factor_ortho:
            self.col_sums.unmap()
            self.execute_kernel(
                self._global_size_ortho, self._local_size_ortho,
                self.krn_compute_col_sums_)

            if self.ocl_set_const_args:
                self.cl_const[4] = self.factor_ortho
                self.krn_weights_.set_arg(10, self.cl_const[4:5])

        if self.ocl_set_const_args:
            self.cl_const[0] = self.learning_rate
            self.cl_const[1] = self.weights_decay
            self.cl_const[2] = self.l1_vs_l2
            self.cl_const[3] = self.gradient_moment
            self.krn_weights_.set_args(
                self.device.skip(6), self.cl_const[0:1], self.cl_const[1:2],
                self.cl_const[2:3], self.cl_const[3:4])
        self.execute_kernel(
            self._global_size_weights, self._local_size_weights,
            self.krn_weights_)

    def gpu_bias_update(self):
        if not self.include_bias:
            return

        self.unmap_vectors(
            self.err_output, self.bias, self.gradient_bias,
            self.accumulated_gradient_bias, self.gradient_bias_with_moment)

        if self.ocl_set_const_args:  # need own constants for weights and bias
            self.cl_const[5] = self.learning_rate_bias
            self.cl_const[6] = self.weights_decay_bias
            self.cl_const[7] = self.l1_vs_l2_bias
            self.cl_const[8] = self.gradient_moment_bias
            self.krn_bias_.set_args(
                self.device.skip(5), self.cl_const[5:6], self.cl_const[6:7],
                self.cl_const[7:8], self.cl_const[8:9])
        self.execute_kernel(
            self._global_size_bias, self._local_size_bias,
            self.krn_bias_)

    def gpu_err_output_update(self):
        """Multiply err_output by activation derivative by output.
        """
        if self.krn_err_output_ is None:
            return
        self.err_output.unmap()
        self.output.unmap()
        self.execute_kernel(
            self._global_size_err_output, self._local_size_err_output,
            self.krn_err_output_)

    def numpy_err_output_update(self):
        """Multiply err_output by activation derivative by output.
        """
        pass

    def print_debug_data(self):
        """
        Show weights statistics
        """
        if not self.logger.isEnabledFor(logging.DEBUG):
            return
        self.weights.map_read()
        self.bias.map_read()
        self.gradient_bias.map_read()
        self.gradient_weights.map_read()
        weights = self.weights.mem
        bias = self.bias.mem
        grad_weights = self.gradient_weights.mem
        grad_bias = self.gradient_bias.mem

        weight_table = PrettyTable("TYPE", "Mean", "StdDev", "Min", "Max")
        weight_table.float_format = ".10"
        for (w_name, w_array) in [("Weight", weights), ("Bias", bias),
                                  ("Grad Weight", grad_weights),
                                  ("Grad Bias", grad_bias)]:
            w_mean = w_stddev = w_min = w_max = None
            if w_array is not None and w_array.size > 0:
                w_mean = numpy.mean(w_array)
                w_stddev = numpy.std(w_array)
                w_min = numpy.min(w_array)
                w_max = numpy.max(w_array)
            weight_table.add_row(w_name, w_mean, w_stddev, w_min, w_max)
        self.debug("\n" + weight_table.get_string())

    def generate_data_for_slave(self, slave):
        return (self.learning_rate, self.weights_decay, self.gradient_moment,
                self.learning_rate_bias, self.weights_decay_bias,
                self.gradient_moment_bias)

    @staticmethod
    def fill_zeros(vector):
        if not vector:
            return
        vector.map_invalidate()
        vector.mem[:] = 0

    def apply_data_from_master(self, data):
        self.learning_rate = data[0]
        self.weights_decay = data[1]
        self.gradient_moment = data[2]
        self.learning_rate_bias = data[3]
        self.weights_decay_bias = data[4]
        self.gradient_moment_bias = data[5]
        self.fill_zeros(self.gradient_weights_with_moment)
        self.fill_zeros(self.gradient_bias_with_moment)
        self.fill_zeros(self.gradient_weights)
        self.fill_zeros(self.gradient_bias)
        self.fill_zeros(self.accumulated_gradient_weights)
        self.fill_zeros(self.accumulated_gradient_bias)

    def generate_data_for_master(self):
        if not self.gradient_changed:
            return None
        self.gradient_changed = False
        self.gradient_weights_with_moment.map_read()
        self.gradient_bias_with_moment.map_read()
        return (self.gradient_weights_with_moment.mem,
                self.gradient_bias_with_moment.mem)

    def apply_data_from_slave(self, data, slave):
        if self.weights:
            self.weights.map_write()
            self.gradient_weights_with_moment.map_write()
            self.gradient_weights_with_moment.mem *= self.gradient_moment
            self.gradient_weights_with_moment.mem += data[0]
            self.weights.mem += self.gradient_weights_with_moment.mem
        if self.bias:
            self.bias.map_write()
            self.gradient_bias_with_moment.map_write()
            self.gradient_bias_with_moment.mem *= self.gradient_moment_bias
            self.gradient_bias_with_moment.mem += data[1]
            self.bias.mem += self.gradient_bias_with_moment.mem

    def drop_slave(self, slave):
        pass

    @staticmethod
    def numpy_gradient_step(weight, gradient, lr, factor_l12, l1_vs_l2,
                            factor_ortho=0, weights_transposed=False):
        gradient = gradient.copy()
        gradient += factor_l12 * ((1.0 - l1_vs_l2) * weight +
                                  0.5 * l1_vs_l2 * numpy.sign(weight))
        if factor_ortho:
            col_sums = (reshape_transposed(weight).sum(axis=1)
                        if weights_transposed else weight.sum(axis=0))
            for i, row in enumerate(gradient):
                row += (col_sums - weight[i]) * factor_ortho / weight.shape[0]
        gradient *= lr
        return gradient

    def run(self):
        self.gradient_changed = True
        super(GradientDescentBase, self).run()
        self.ocl_set_const_args = False


class NNWorkflow(AcceleratedWorkflow):
    """Base class for neural network workflow.

    Attributes:
        repeater: Repeater unit.
        loader: loader.Loader unit.
        forwards: list of the forward propagation (Forward) units.
        evaluator: evaluator.* unit.
        decision: decision.Decision unit.
        gds: list of the gradient descent units.
    """
    def __init__(self, workflow, **kwargs):
        super(NNWorkflow, self).__init__(workflow, **kwargs)
        self._repeater = Repeater(self)
        self._loader = None
        self._forwards = []
        self._evaluator = None
        self._decision = None
        self._gds = []

    @property
    def repeater(self):
        return self._repeater

    @property
    def forwards(self):
        return self._forwards

    @property
    def gds(self):
        return self._gds

    @property
    def loader(self):
        if self._loader is None:
            raise AttributeError(
                "No loader unit currently exists. You must set it first.")
        return self._loader

    @loader.setter
    def loader(self, value):
        if not isinstance(value, (Loader, Avatar)):
            raise TypeError(
                "Loader must be an instance of veles.loader.Loader")
        self._loader = value

    @property
    def decision(self):
        if self._decision is None:
            raise AttributeError(
                "No decision unit currently exists. You must set it first.")
        return self._decision

    @decision.setter
    def decision(self, value):
        if not isinstance(value, DecisionBase):
            raise TypeError(
                "Decision must be an instance of veles.znicz.decision."
                "DecisionBase")
        self._decision = value

    @property
    def evaluator(self):
        if self._evaluator is None:
            raise AttributeError(
                "No evaluator unit currently exists. You must set it first.")
        return self._evaluator

    @evaluator.setter
    def evaluator(self, value):
        if value is None:
            raise ValueError("Evaluator may not be None")
        if not isinstance(value, EvaluatorBase) and (
                not hasattr(value, "output") or "input" not in value.demanded):
            raise TypeError(
                "Evaluator must be either an instance of veles.znicz.evaluator"
                ".EvaluatorBase or demand \"input\" and provide \"output\" "
                "(got %s)." % type(value))
        self._evaluator = value

    def export(self, file_name):
        """Exports workflow for use on DTV.
        """
        exported = [u for u in self if hasattr(u, "export")]
        if len(exported) == 0:
            raise ValueError("No units support export. Implement export() "
                             "method in at least one.")
        obj = {"workflow": self.name,
               "checksum": self.checksum,
               "units": [{"class": {"name": unit.__class__.__name__,
                                    "uuid": unit.__class__.__id__},
                          "data": unit.export()}
                         for unit in exported]}
        for index, unit in enumerate(exported):
            obj["units"][index]["links"] = [
                exported.index(u) for u in sorted(unit.links_to.keys())
                if u in exported]
        # TODO(v.markovtsev): check the resulting graph's connectivity
        # TODO(v.markovtsev): check for single entry and exit points

        import json

        arrays = []

        def array_file_name(arr, index):
            return "%04d_%s" % (index, "x".join(arr.shape))

        def export_numpy_array(arr):
            if isinstance(arr, numpy.ndarray):
                arrays.append(arr)
                return array_file_name(arr, len(arrays) - 1)
            raise TypeError("Objects of class other than numpy.ndarray are "
                            "not supported")
        try:
            with tarfile.open(file_name, "w:gz") as tar:
                io = six.BytesIO()
                json.dump(obj, io, indent=4, sort_keys=True,
                          default=export_numpy_array)
                ti = tarfile.TarInfo("contents.json")
                ti.size = io.tell()
                ti.mode = int("666", 8)
                io.seek(0)
                tar.addfile(ti, fileobj=io)
                for index, arr in enumerate(arrays):
                    io = six.BytesIO()
                    numpy.save(io, arr)
                    ti = tarfile.TarInfo(array_file_name(arr, index) + ".npy")
                    ti.size = io.tell()
                    ti.mode = int("666", 8)
                    io.seek(0)
                    tar.addfile(ti, fileobj=io)
        except:
            self.exception("Failed to export to %s", file_name)


class NNSnapshotterBase(SnapshotterBase):
    def __init__(self, workflow, **kwargs):
        super(NNSnapshotterBase, self).__init__(workflow, **kwargs)
        self.has_invalid_values = Bool(False)

    def _log_attr(self, unit, attr, logged):
        val = getattr(unit, attr, None)
        if val is None:
            return
        mem = getattr(val, "mem", None)
        if mem is None:
            return
        val.map_read()
        if id(mem) not in logged:
            self.has_invalid_values <<= bool(
                numpy.count_nonzero(numpy.isnan(mem)) or
                numpy.count_nonzero(numpy.isinf(mem)))
            args = ("%s: %s: min max avg: %.6f %.6f %.6f%s",
                    unit.__class__.__name__, attr,
                    mem.min(), mem.max(), numpy.average(mem),
                    " has invalid values" if self.has_invalid_values else "")
            if self.has_invalid_values:
                self.error(*args)
            else:
                self.info(*args)
            logged.add(id(mem))

    def run(self):
        super(NNSnapshotterBase, self).run()
        logged = set()
        for u in self.workflow.start_point.dependent_units():
            for attr in ("input", "weights", "bias", "output",
                         "err_output", "err_input"):
                self._log_attr(u, attr, logged)
        del logged
        _, dt = timeit(gc.collect)
        if dt > 1.0:
            self.warning("gc.collect() took %.1f sec", dt)


class NNSnapshotterToFile(NNSnapshotterBase, SnapshotterToFile):
    MAPPING = "nnfile"


class NNSnapshotterToDB(NNSnapshotterBase, SnapshotterToDB):
    MAPPING = "nnodbc"
