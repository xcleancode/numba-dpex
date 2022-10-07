#! /usr/bin/env python

# SPDX-FileCopyrightText: 2020 - 2022 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import dpctl
import numpy as np

import numba_dpex as dpex


@dpex.kernel
def gemm(a, b, c):
    """
    A basic DGEMM implemented as a ``kernel`` function.
    """
    i = dpex.get_global_id(0)
    j = dpex.get_global_id(1)
    if i >= c.shape[0] or j >= c.shape[1]:
        return
    c[i, j] = 0
    for k in range(c.shape[0]):
        c[i, j] += a[i, k] * b[k, j]


# Array dimensions
X = 1024
Y = 16
global_size = X, X

griddim = X, X
blockdim = Y, Y


def driver(a, b, c):
    # Invoke the kernel
    gemm[griddim, blockdim](a, b, c)


def main():
    a = np.arange(X * X, dtype=np.float32).reshape(X, X)
    b = np.array(np.random.random(X * X), dtype=np.float32).reshape(X, X)
    c = np.ones_like(a).reshape(X, X)

    # Use the environment variable SYCL_DEVICE_FILTER to change the default device.
    # See https://github.com/intel/llvm/blob/sycl/sycl/doc/EnvironmentVariables.md#sycl_device_filter.
    device = dpctl.select_default_device()
    print("Using device ...")
    device.print_device_info()

    with dpctl.device_context(device):
        driver(a, b, c)

    # Host compute using standard NumPy
    Amat = np.matrix(a)
    Bmat = np.matrix(b)
    Cans = Amat * Bmat

    # Check result
    assert np.allclose(c, Cans)

    print("Done...")


if __name__ == "__main__":
    main()
