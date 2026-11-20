# -*- coding: utf-8 -*-

import torch

# 是否支持 CUDA
print("CUDA 可用:", torch.cuda.is_available())

# GPU 设备数量
print("GPU 数量:", torch.cuda.device_count())

# 当前默认 GPU 的索引
print("当前 GPU:", torch.cuda.current_device())

# GPU 型号名称
print("GPU 型号:", torch.cuda.get_device_name(0))

# PyTorch 版本与编译时绑定的 CUDA 版本
print("PyTorch 版本:", torch.__version__)
print("CUDA 版本:", torch.version.cuda)