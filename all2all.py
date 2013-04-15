"""
Created on Mar 20, 2013

All2All filters.

TODO(a.kazantsev): implement analigned matrix sizes in filters by expanding them.

@author: Kazantsev Alexey <a.kazantsev@samsung.com>
"""
import filters
import numpy
import pyopencl
import opencl


class All2All(filters.OpenCLFilter):
    """All2All layer to layer.

    State:
        input: input as Batch.
        output: output as Batch.
        weights: weights as Vector.
        bias: bias as Vector.

    Attributes:
        output_shape: shape of the output layer.
        weights_amplitude: amplitude of the default random distribution of weights.
        rand: numpy-style random generator function.
        krn_: OpenCL kernel.
    """
    def __init__(self, output_shape = None, device=None, weights_amplitude = 0.05, rand = numpy.random.rand, \
                 unpickling = 0):
        super(All2All, self).__init__(unpickling=unpickling, device=device)
        self.krn_ = None
        if unpickling:
            return
        self.input = filters.Batch()
        self.output = filters.Batch()
        self.weights = filters.Vector()
        self.bias = filters.Vector()
        self.output_shape = output_shape
        self.weights_amplitude = weights_amplitude
        self.rand = rand

    def _initialize(self, cl_src):
        n_weights = self.input.batch.size // self.input.batch.shape[0] * numpy.prod(self.output_shape)
        if self.weights.v == None or self.weights.v.size != n_weights:
            self.weights.v = filters.aligned_zeros([n_weights])
            self.weights.v[:] = self.rand(self.weights.v.size)
            self.weights.v *= 2.0 * self.weights_amplitude
            self.weights.v -= self.weights_amplitude
        if self.bias.v == None or self.bias.v.size != numpy.prod(self.output_shape):
            self.bias.v = filters.aligned_zeros([numpy.prod(self.output_shape)])
            self.bias.v[:] = self.rand(self.bias.v.size)
            self.bias.v *= 2.0 * self.weights_amplitude
            self.bias.v -= self.weights_amplitude

        output_size = self.input.batch.shape[0] * numpy.prod(self.output_shape)
        if self.output.batch == None or self.output.batch.size != output_size:
            self.output.batch = filters.aligned_zeros([self.input.batch.shape[0], numpy.prod(self.output_shape)])

        mf = pyopencl.mem_flags
        if self.input.batch_ == None:
            self.input.batch_ = pyopencl.Buffer(self.device.context_, mf.READ_WRITE | mf.USE_HOST_PTR, \
                                                hostbuf=self.input.batch)
        if self.output.batch_ == None:
            self.output.batch_ = pyopencl.Buffer(self.device.context_, mf.READ_WRITE | mf.USE_HOST_PTR, \
                                                 hostbuf=self.output.batch)
        if self.weights.v_ == None:
            self.weights.v_ = pyopencl.Buffer(self.device.context_, mf.READ_WRITE | mf.USE_HOST_PTR, \
                                              hostbuf=self.weights.v)
        if self.bias.v_ == None:
            self.bias.v_ = pyopencl.Buffer(self.device.context_, mf.READ_WRITE | mf.USE_HOST_PTR, \
                                           hostbuf=self.bias.v)

        output_size = int(numpy.prod(self.output_shape))

        if self.krn_ == None:
            defines = ("#define BLOCK_SIZE %d\n"
                       "#define AB_WIDTH %d\n"
                       "#define B_HEIGHT %d\n\n") % \
                       (self.device.info.BLOCK_SIZE, self.weights.v.size // output_size, output_size)
            fin = open("cl/"+cl_src, "r")
            s = defines + fin.read()
            fin.close()
            fout = open("cache/"+cl_src, "w")
            fout.write(s)
            fout.close()

            prg = pyopencl.Program(self.device.context_, s).build()

            self.krn_ = pyopencl.Kernel(prg, "FEED_LAYER")
            self.krn_.set_arg(0, self.input.batch_)
            self.krn_.set_arg(1, self.weights.v_)
            self.krn_.set_arg(2, self.output.batch_)
            self.krn_.set_arg(3, self.bias.v_)

    def print_times(self):
        """Show some statistics.
        """
        print("Processed %d samples with %d weights within %.2f seconds: %s" % \
              (self.output.batch.shape[0], self.weights.v.size, \
               self.output.mtime - self.input.mtime, self.__class__.__name__))


class All2AllTanh(All2All):
    """All2All layer to layer with scaled tanh() activation.
    """
    def initialize(self):
        self._initialize("feed_tanh.cl")

    def run(self):
        """Forward propagation from batch. 
        """
        output_size = int(numpy.prod(self.output_shape))
        global_size = [output_size, self.output.batch.shape[0]]
        local_size = [self.device.info.BLOCK_SIZE, self.device.info.BLOCK_SIZE]
        event = pyopencl.enqueue_nd_range_kernel(self.device.queue_, self.krn_, global_size, local_size)
        event.wait()
        self.output.update()
        self.print_times()


class All2AllSoftmax(All2All):
    """All2All layer to layer with softmax activation.
    
    Currently, we will calculate softmax partially on cpu.
    """
    def initialize(self):
        self._initialize("feed_exp.cl")

    def run(self):
        """Forward propagation from batch. 
        """
        output_size = int(numpy.prod(self.output_shape))
        global_size = [output_size, self.output.batch.shape[0]]
        local_size = [self.device.info.BLOCK_SIZE, self.device.info.BLOCK_SIZE]
        ev = pyopencl.enqueue_nd_range_kernel(self.device.queue_, self.krn_, global_size, local_size)

        arr, event = pyopencl.enqueue_map_buffer(queue=self.device.queue_, buf=self.output.batch_, \
                flags=opencl.CL_MAP_READ, offset=0, shape=self.output.batch.shape, \
                dtype=self.output.batch.dtype, order="C", wait_for=[ev], is_blocking=False)

        event.wait()
        arr.base.release(queue=self.device.queue_)

        for sample in self.output.batch:
            rsum = 1.0 / sample.sum()
            sample *= rsum

        self.output.update()
        self.print_times()
