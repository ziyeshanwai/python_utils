import tensorrt as trt
import numpy as np
import os
import cv2
import pycuda.driver as cuda
import pycuda.autoinit


class HostDeviceMem(object):
    def __init__(self, host_mem, device_mem):
        self.host = host_mem
        self.device = device_mem

    def __str__(self):
        return "Host:\n" + str(self.host) + "\nDevice:\n" + str(self.device)

    def __repr__(self):
        return self.__str__()


class TrtModel:

    def __init__(self, engine_path, max_batch_size=1, dtype=np.float32):

        self.engine_path = engine_path
        self.dtype = dtype
        self.logger = trt.Logger(trt.Logger.WARNING)
        self.runtime = trt.Runtime(self.logger)
        self.engine = self.load_engine(self.runtime, self.engine_path)
        self.max_batch_size = max_batch_size
        self.inputs, self.outputs, self.bindings, self.stream = self.allocate_buffers()
        self.context = self.engine.create_execution_context()

    @staticmethod
    def load_engine(trt_runtime, engine_path):
        trt.init_libnvinfer_plugins(None, "")
        with open(engine_path, 'rb') as f:
            engine_data = f.read()
        engine = trt_runtime.deserialize_cuda_engine(engine_data)
        return engine

    def allocate_buffers(self):

        inputs = []
        outputs = []
        bindings = []
        stream = cuda.Stream()

        for binding in self.engine:
            size = trt.volume(self.engine.get_binding_shape(binding)) * self.max_batch_size
            host_mem = cuda.pagelocked_empty(size, self.dtype)
            device_mem = cuda.mem_alloc(host_mem.nbytes)

            bindings.append(int(device_mem))

            if self.engine.binding_is_input(binding):
                inputs.append(HostDeviceMem(host_mem, device_mem))
            else:
                outputs.append(HostDeviceMem(host_mem, device_mem))

        return inputs, outputs, bindings, stream

    def __call__(self, x: np.ndarray, batch_size=2):

        x = x.astype(self.dtype)

        np.copyto(self.inputs[0].host, x.ravel())

        for inp in self.inputs:
            cuda.memcpy_htod_async(inp.device, inp.host, self.stream)

        self.context.execute_async(batch_size=batch_size, bindings=self.bindings, stream_handle=self.stream.handle)
        for out in self.outputs:
            cuda.memcpy_dtoh_async(out.host, out.device, self.stream)

        self.stream.synchronize()
        return [out.host.reshape(batch_size, -1) for out in self.outputs]


if __name__ == "__main__":
    batch_size = 1
    root_data = os.path.split(os.path.abspath(__file__))[0]
    trt_engine_path = os.path.join(root_data, "data", "bs_swit.trt")
    model = TrtModel(trt_engine_path)
    shape = model.engine.get_binding_shape(0)
    image = cv2.imread(os.path.join(root_data, "data", "050.jpg"))
    image = image[128:, 100:868]
    image = cv2.copyMakeBorder(image, 0, 0, 192, 192, borderType=cv2.BORDER_CONSTANT, value=0)
    image = (cv2.resize(image, (224, 224)).transpose((2, 0, 1)) / 255.0).astype(np.float32)
    data = image[np.newaxis, :, :, :]
    result = model(data, batch_size)
    print(result)