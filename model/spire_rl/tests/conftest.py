import sys

import torch

if sys.platform == "darwin":
    # Local macOS installs that need KMP_DUPLICATE_LIB_OK can crash inside
    # multi-threaded OpenMP kernels; the tests do not need intra-op threads.
    torch.set_num_threads(1)
