"""
Created on Nov 8, 2013

Will test correctness of OpenCL matrix multiplication.

Copyright (c) 2013 Samsung Electronics Co., Ltd.
"""


import logging
import numpy
import os
import unittest

from veles.config import root
import veles.formats as formats
import veles.opencl as opencl
import veles.opencl_types as opencl_types
from veles.opencl_units import OpenCLUnit
import veles.random_generator as rnd
from veles.tests.dummy_workflow import DummyWorkflow


class TestMatrixMultiplication(unittest.TestCase):
    def setUp(self):
        root.common.unit_test = True
        root.common.plotters_disabled = True
        self.device = opencl.Device()

    def tearDown(self):
        del self.device

    def _do_cpu_tst(self):
        """Pure single core CPU test
        """
        dtype = (numpy.complex128 if self.a.v.dtype in (
            numpy.complex64, numpy.complex128) else numpy.float64)
        a = numpy.empty(self.a.v.shape, dtype=dtype)
        a[:] = self.a.v[:]
        bt = self.b.v.transpose()
        b = numpy.empty(bt.shape, dtype=dtype)
        b[:] = bt[:]
        bias = numpy.empty(self.bias.v.shape, dtype=dtype)
        bias[:] = self.bias.v[:]
        c = numpy.empty(self.c[0].shape, dtype=dtype)
        numpy.dot(a, b, c)
        c[:] += bias
        c *= 0.6666
        numpy.tanh(c, c)
        c *= 1.7159
        return c

    def _prepare_tsts(self, BLOCK_SIZE,
                      dtype=opencl_types.dtypes[root.common.dtype],
                      AB_WIDTH=1371, B_HEIGHT=11735, A_HEIGHT=171):
        self.AB_WIDTH = AB_WIDTH
        self.B_HEIGHT = B_HEIGHT
        self.A_HEIGHT = A_HEIGHT

        self.a = formats.Vector()
        self.a.v = numpy.zeros([self.A_HEIGHT * self.AB_WIDTH], dtype=dtype)
        rnd.get().fill(self.a.v, -0.1, 0.1)
        self.a.v = self.a.v.reshape([self.A_HEIGHT, self.AB_WIDTH])

        self.b = formats.Vector()
        self.b.v = numpy.zeros([self.B_HEIGHT * self.AB_WIDTH], dtype=dtype)
        rnd.get().fill(self.b.v, -0.1, 0.1)
        self.b.v = self.b.v.reshape([self.B_HEIGHT, self.AB_WIDTH])

        self.bias = formats.Vector()
        self.bias.v = numpy.zeros([self.B_HEIGHT], dtype=dtype)
        rnd.get().fill(self.bias.v, -0.1, 0.1)

        self.c = formats.Vector()
        self.c.v = numpy.zeros([2, self.A_HEIGHT, self.B_HEIGHT], dtype=dtype)

    def _cleanup_after_tsts(self):
        del(self.c)
        del(self.bias)
        del(self.b)
        del(self.a)
        del(self.A_HEIGHT)
        del(self.B_HEIGHT)
        del(self.AB_WIDTH)

    def _do_test(self, device, BLOCK_SIZE):
        """Do test for specific context
        """
        self.a.initialize(device)
        self.b.initialize(device)
        self.c[:] = 0
        self.c.initialize(device)
        self.bias.initialize(device)

        obj = OpenCLUnit(DummyWorkflow())
        obj.initialize(device=device)
        obj.cl_sources_["forward.cl"] = {}
        defines = {
            "ACTIVATION_TANH": 1,
            "BLOCK_SIZE": BLOCK_SIZE,
            "H": self.AB_WIDTH,
            "Y": self.B_HEIGHT,
            "BATCH": self.A_HEIGHT}
        obj.build_program(defines, os.path.join(root.common.cache_dir,
                                                "test.cl"))

        krn = obj.get_kernel("feed_layer")
        krn.set_arg(0, self.a.v_)
        krn.set_arg(1, self.b.v_)
        krn.set_arg(2, self.c.v_)
        krn.set_arg(3, self.bias.v_)

        global_size = [formats.roundup(self.B_HEIGHT, BLOCK_SIZE),
                       formats.roundup(self.A_HEIGHT, BLOCK_SIZE)]
        local_size = [BLOCK_SIZE, BLOCK_SIZE]

        event = self.device.queue_.execute_kernel(krn, global_size, local_size)
        event.wait()

        self.c.map_read()

    def test_matrix_multiplication(self):
        self.rnd = rnd.Rand()
        self.rnd.seed("/dev/urandom", dtype=numpy.int32, count=1024)
        block_size = self.device.device_info.BLOCK_SIZE[root.common.dtype]
        N = 1000
        logging.info("Will test %d matrix multiplications "
                     "with BLOCK_SIZE = %d" % (N, block_size))
        j = 0
        for i in range(0, N, 29):
            AB_WIDTH = self.rnd.randint(1, ((i // 10) + 1) * 100)
            B_HEIGHT = self.rnd.randint(1, ((i // 10) + 1) * 10)
            A_HEIGHT = self.rnd.randint(1, ((i // 10) + 1) * 10)
            if j % 2 == 0:
                AB_WIDTH = formats.roundup(AB_WIDTH, block_size)
                B_HEIGHT = formats.roundup(B_HEIGHT, block_size)
                A_HEIGHT = formats.roundup(A_HEIGHT, block_size)
            j += 1
            logging.info("%d: [%d, %d] * [%d, %d] = [%d, %d]" %
                         (i, AB_WIDTH, A_HEIGHT, B_HEIGHT, AB_WIDTH,
                          A_HEIGHT, B_HEIGHT))
            self._prepare_tsts(block_size, AB_WIDTH=AB_WIDTH,
                               B_HEIGHT=B_HEIGHT, A_HEIGHT=A_HEIGHT)
            c = self._do_cpu_tst()
            self._do_test(self.device, block_size)
            max_diff = numpy.fabs(c.ravel() - self.c[0].ravel()).max()
            self.assertLess(max_diff, 0.0001,
                            "Result differs by %.6f" % (max_diff))
            num_nz = numpy.count_nonzero(self.c[1].ravel())
            self.assertEqual(
                num_nz, 0,
                "Written some values outside of the target array bounds")
            self._cleanup_after_tsts()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    # import sys;sys.argv = ['', 'Test.testName']
    unittest.main()
