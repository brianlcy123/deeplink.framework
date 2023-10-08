import acl
import os
import numpy as np
import torch
import atexit


# the range for dynamic shape
MAX_RANGE = 128

# rule for mem
ACL_MEM_MALLOC_HUGE_FIRST = 0
ACL_MEM_MALLOC_HUGE_ONLY = 1
ACL_MEM_MALLOC_NORMAL_ONLY = 2
# rule for memory copy
ACL_MEMCPY_HOST_TO_HOST = 0
ACL_MEMCPY_HOST_TO_DEVICE = 1
ACL_MEMCPY_DEVICE_TO_HOST = 2
ACL_MEMCPY_DEVICE_TO_DEVICE = 3
# error code
ACL_SUCCESS = 0
# images format
IMG_EXT = ['.jpg', '.JPG', '.png', '.PNG', '.bmp', '.BMP', '.jpeg', '.JPEG']
# data format
NPY_FLOAT32 = 11
ACL_DT_UNDEFINED = -1
ACL_FLOAT = 0
ACL_FLOAT16 = 1
ACL_INT8 = 2
ACL_INT32 = 3
ACL_UINT8 = 4
ACL_INT16 = 6
ACL_UINT16 = 7
ACL_UINT32 = 8
ACL_INT64 = 9
ACL_UINT64 = 10
ACL_DOUBLE = 11
ACL_BOOL = 12
ACL_COMPLEX64 = 16

ACL_MDL_PRIORITY_INT32 = 0
ACL_MDL_LOAD_TYPE_SIZET = 1
ACL_MDL_PATH_PTR = 2
ACL_MDL_MEM_ADDR_PTR = 3
ACL_MDL_MEM_SIZET = 4 
ACL_MDL_WEIGHT_ADDR_PTR = 5
ACL_MDL_WEIGHT_SIZET = 6
ACL_MDL_WORKSPACE_ADDR_PTR = 7
ACL_MDL_WORKSPACE_SIZET = 8
ACL_MDL_INPUTQ_NUM_SIZET = 9
ACL_MDL_INPUTQ_ADDR_PTR = 10
ACL_MDL_OUTPUTQ_NUM_SIZET = 11
ACL_MDL_OUTPUTQ_ADDR_PTR = 12
ACL_MDL_WORKSPACE_MEM_OPTIMIZE = 13

def get_np_dtype(dtype):
    if dtype == ACL_FLOAT:
        return np.float32
    elif dtype == ACL_INT64:
        return np.int64
    elif dtype == ACL_INT32:
        return np.int32
    elif dtype == ACL_BOOL:
        return np.bool_
    elif dtype == ACL_DOUBLE:
        return np.float64
    elif dtype == ACL_COMPLEX64:
        return np.complex64
    elif dtype == ACL_FLOAT16:
        return np.float16
    raise RuntimeError("unsupported np dtype!")


def get_tensor_dtype(dtype):
    if dtype == ACL_FLOAT:
        return torch.float32
    elif dtype == ACL_INT64:
        return torch.int64
    elif dtype == ACL_FLOAT16:
        return torch.float16
    elif dtype == ACL_INT32:
        return torch.int32
    elif dtype == ACL_BOOL:
        return torch.bool
    elif dtype == ACL_DOUBLE:
        return torch.float64
    elif dtype == ACL_COMPLEX64:
        return torch.complex64
    raise RuntimeError(f"can not convert acl dtype:{dtype} to torch dtype")


buffer_method = {
    "in": acl.mdl.get_input_size_by_index,
    "out": acl.mdl.get_output_size_by_index
    }

def check_ret(message, ret):
    if ret != ACL_SUCCESS:
        raise Exception("{} failed ret={}"
                        .format(message, ret))


class MemoryPool:
    def __init__(self):
        self.work_ptr = None
        self.weight_ptr = None
        atexit.register(self.release_memory)
        self.init_work_weight_ptr()

    def init_work_weight_ptr(self):
        if self.work_ptr is None:
            self.work_size = 13 * 1024 * 1024 * 1024
            self.work_ptr, ret = acl.rt.malloc(self.work_size,
                                                ACL_MEM_MALLOC_HUGE_FIRST)
            check_ret("acl.rt.malloc", ret)

    def release_memory(self):
        print("Release bufferPtr from MemoryPool.")
        if self.work_ptr is not None:
            ret = acl.rt.free(self.work_ptr)
            check_ret("acl.rt.free", ret)
            self.work_ptr = None

        if self.weight_ptr is not None:
            ret = acl.rt.free(self.weight_ptr)
            check_ret("acl.rt.free", ret)
            self.weight_ptr = None


memory_pool = MemoryPool()


class AscendExecutor(object):
    def __init__(self, device_id, model_path) -> None:
        self.device_id = device_id          # int
        self.model_path = model_path        # str
        self.model_id = None                # pointer
        self.context = None                 # pointer
        self.model_desc = None              # pointer when using
        self.num_inputs = 0
        self.num_outputs = 0
        self.input_size = []
        self.output_size = []
        self.output_dims = []
        self.output_dtypes = []
        self.output_data = []
        self.input_shape = []
        self.input_dataset = acl.mdl.create_dataset()
        self.input_data_buffers = []
        self.output_dataset = acl.mdl.create_dataset()
        self.output_data_buffers = []

        self.init_resource()

    def __del__(self):
        self.release_resource()

    def release_resource(self):
        print("Releasing resources stage:")
        if self.model_id > -1:
            ret = acl.mdl.unload(self.model_id)
            check_ret("acl.mdl.unload", ret)
            self.model_id = -1
        if self.model_desc:
            acl.mdl.destroy_desc(self.model_desc)
            self.model_desc = None

    def load_model(self):
        work_size, weight_size, ret = acl.mdl.query_size(self.model_path)
        check_ret("acl.mdl.query_size", ret)
        weight_ptr, ret = acl.rt.malloc(weight_size,
                                              ACL_MEM_MALLOC_HUGE_FIRST)
        check_ret("acl.rt.malloc", ret)
        config_handle = acl.mdl.create_config_handle()
        ret = acl.mdl.set_config_opt(config_handle, ACL_MDL_LOAD_TYPE_SIZET, 2)
        check_ret("set_config_opt", ret) 

        ret = acl.mdl.set_config_opt(config_handle, ACL_MDL_PATH_PTR, self.model_path)
        check_ret("set_config_opt", ret)

        ret = acl.mdl.set_config_opt(config_handle, ACL_MDL_WEIGHT_ADDR_PTR, weight_ptr)
        check_ret("set_config_opt", ret)

        ret = acl.mdl.set_config_opt(config_handle, ACL_MDL_WEIGHT_SIZET, weight_size)
        check_ret("set_config_opt", ret)

        ret = acl.mdl.set_config_opt(config_handle, ACL_MDL_WORKSPACE_ADDR_PTR, memory_pool.work_ptr)
        check_ret("set_config_opt", ret)

        ret = acl.mdl.set_config_opt(config_handle, ACL_MDL_WORKSPACE_SIZET, work_size)
        check_ret("set_config_opt", ret)

        ret = acl.mdl.set_config_opt(config_handle, ACL_MDL_WORKSPACE_MEM_OPTIMIZE, 1)
        check_ret("set_config_opt", ret)

        self.model_id, ret = acl.mdl.load_with_config(config_handle)
        check_ret("acl.mdl.load_with_config", ret)
        print("model_id:{}".format(self.model_id))

        self.model_desc = acl.mdl.create_desc()
        ret = acl.mdl.get_desc(self.model_desc, self.model_id)
        check_ret("acl.mdl.get_desc", ret)

    def init_resource(self):
        print("init resource stage:")

        self.load_model()
        self.num_inputs = acl.mdl.get_num_inputs(self.model_desc)
        self.num_outputs = acl.mdl.get_num_outputs(self.model_desc)
        for i in range(self.num_inputs):
            temp_buffer_size = acl.mdl.get_input_size_by_index(self.model_desc, i)
            self.input_size.append(temp_buffer_size)
            input_dims, ret = acl.mdl.get_input_dims(self.model_desc, i)
            check_ret("acl.mdl.get_input_dims", ret)
            self.input_shape.append(input_dims)
            data_buf = acl.create_data_buffer(0, 1)
            self.input_data_buffers.append(data_buf)
            _, ret = acl.mdl.add_dataset_buffer(self.input_dataset, data_buf)
            check_ret("acl.add_dataset_buffer", ret)

        for i in range(self.num_outputs):
            temp_buffer_size = acl.mdl.get_output_size_by_index(self.model_desc, i)
            dtype = acl.mdl.get_output_data_type(self.model_desc, i)
            dims, ret = acl.mdl.get_output_dims(self.model_desc, i)
            check_ret("acl.mdl.get_output_dims", ret)
            dims = dims["dims"]
            if temp_buffer_size == 0:
                temp_buffer_size = 1
                for idx, dim in enumerate(dims):
                    if dim > -1:
                        temp_buffer_size *= dim
                    else:
                        temp_buffer_size *= MAX_RANGE
                        dims[idx] = MAX_RANGE
                np_dtype = get_np_dtype(dtype)
                temp_buffer_size *= np.dtype(np_dtype).itemsize

            if temp_buffer_size == 0:
                temp_buffer_size = 1
            self.output_dtypes.append(get_tensor_dtype(dtype))
            self.output_dims.append(dims)
            self.output_size.append(temp_buffer_size)
            data_buf = acl.create_data_buffer(0, 1)
            self.output_data_buffers.append(data_buf)
            _, ret = acl.mdl.add_dataset_buffer(self.output_dataset, data_buf)
            check_ret("acl.add_dataset_buffer", ret)

        print("init resource success")

    def _prepare_input(self, images, dims):
        assert self.num_inputs == len(images)
        zero_tensor = torch.randn(1).xpu()
        for i in range(self.num_inputs):
            buffer_size = self.input_size[i]
            if dims is not None and i in dims.keys():
                tot_size = 1
                for elem in dims[i]:
                    tot_size *= elem
                dtype = acl.mdl.get_input_data_type(self.model_desc, i)
                np_dtype = get_np_dtype(dtype)
                buffer_size = tot_size * np.dtype(np_dtype).itemsize

            if buffer_size == 0:
                buffer_size = 1
                ptr = zero_tensor.data_ptr()
            else:
                ptr = images[i].data_ptr()

            ret = acl.update_data_buffer(self.input_data_buffers[i], ptr, buffer_size)
            check_ret("acl.update_data_buffer", ret)
            
            if dims is not None and i in dims.keys():
                dtype = acl.mdl.get_input_data_type(self.model_desc, i)
                format = acl.mdl.get_input_format(self.model_desc, i)
                tensorDesc = acl.create_tensor_desc(dtype, dims[i], format)
                dataset, ret = acl.mdl.set_dataset_tensor_desc(self.input_dataset,
                                                tensorDesc, i)
                check_ret("acl.mdl.set_dataset_tensor_desc", ret)
                assert(dataset == self.input_dataset)            

    def _prepare_output(self, output_tensor):
        for i in range(self.num_outputs):
            item = torch.empty(self.output_dims[i], dtype=self.output_dtypes[i], device='xpu')
            output_tensor.append(item)
            ret = acl.update_data_buffer(self.output_data_buffers[i], item.data_ptr(), self.output_size[i])
            check_ret("acl.update_data_buffer", ret)

    def _prepare_tmp_output(self):
        for i in range(self.num_outputs):
            temp_buffer, ret = acl.rt.malloc(self.output_size[i],
                            ACL_MEM_MALLOC_HUGE_FIRST)            
            ret = acl.update_data_buffer(self.output_data_buffers[i], temp_buffer, self.output_size[i])
            check_ret("acl.update_data_buffer", ret)
            self.output_data.append(temp_buffer)
            

    def _prepare_real_output(self, output_tensor):
        for i in range(self.num_outputs):
            out = acl.mdl.get_dataset_tensor_desc(self.output_dataset, i)
            tsize = acl.get_tensor_desc_num_dims(out)
            out_dim = []
            tot_size = 1
            for d in range(tsize):
                out_dim.append(acl.get_tensor_desc_dim(out, d))
                tot_size *= out_dim[-1]
            dtype = acl.mdl.get_output_data_type(self.model_desc, i)
            np_dtype = get_np_dtype(dtype)
            tot_size *= np.dtype(np_dtype).itemsize
            item = torch.empty(out_dim, dtype=self.output_dtypes[i], device='xpu')
            output_tensor.append(item)
            ret = acl.rt.memcpy(item.data_ptr(),
                                tot_size,
                                self.output_data[i],
                                tot_size,
                                ACL_MEMCPY_DEVICE_TO_DEVICE)
            check_ret("acl.rt.memcpy", ret)            

    def run(self, images, dims=None, max_range=128):
        global MAX_RANGE
        if max_range > 128:
            MAX_RANGE = max_range
        else:
            MAX_RANGE = 128

        assert len(images) > 0
        input = list(map(lambda x: x.xpu(), images))
        self._prepare_input(input, dims)
        output = []
        if dims is not None:
            self._prepare_tmp_output()
            self.forward()
            self._prepare_real_output(output)
        else:
            self._prepare_output(output)
            self.forward()
        self._destroy_databuffer()
        return output

    def forward(self):
        ret = acl.mdl.execute(self.model_id,
                              self.input_dataset,
                              self.output_dataset)
        check_ret("acl.mdl.execute", ret)

    def _destroy_databuffer(self):
        while self.output_data:
            item = self.output_data.pop()
            ret = acl.rt.free(item)
            check_ret("acl.rt.free", ret)


class AscendModel():
    def __init__(self, device_id, model_path) -> None:
        atexit.register(self.cleanup)
        self.exe = AscendExecutor(device_id, model_path)

    def run(self, images, dims=None, max_range=128):
        return self.exe.run(images, dims, max_range)

    def cleanup(self):
        if hasattr(self, 'exe'):
            del self.exe


if __name__ == '__main__':
    current_dir = os.path.dirname(os.path.abspath(__file__))
    model_path = os.path.join(current_dir, "build", "demo_add_add.om")

    exe = AscendExecutor(0, model_path)
    
    # make input data
    input_data = np.random.randn(1, 1, 28, 28)

    exe.run([input_data])

    print("*****run finish******")
    exe.release_resource()
