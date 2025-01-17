# SPDX-FileCopyrightText: 2020 - 2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import dpctl
import dpctl.tensor as dpt
import dpnp
import numpy as np
import pytest

from numba_dpex import dpjit
from numba_dpex.tests._helper import assert_auto_offloading, filter_strings

""" Following cases, dpnp raises NotImplementedError"""

list_of_binary_ops = [
    "greater",
    "greater_equal",
    "less",
    "less_equal",
    "not_equal",
    "equal",
    "logical_and",
    "logical_or",
    "logical_xor",
]


@pytest.fixture(params=list_of_binary_ops)
def binary_op(request):
    return request.param


list_of_unary_ops = [
    "isinf",
    "isfinite",
    "isnan",
]


@pytest.fixture(params=list_of_unary_ops)
def unary_op(request):
    return request.param


list_of_dtypes = [
    dpnp.int32,
    dpnp.int64,
    dpnp.float32,
    dpnp.float64,
]


@pytest.fixture(params=list_of_dtypes)
def input_arrays(request):
    # The size of input and out arrays to be used
    N = 2048
    a = dpnp.array(dpnp.random.random(N), request.param)
    b = dpnp.array(dpnp.random.random(N), request.param)
    return a, b


@pytest.mark.xfail
@pytest.mark.parametrize("filter_str", filter_strings)
def test_binary_ops(filter_str, binary_op, input_arrays):
    a, b = input_arrays
    binop = getattr(dpnp, binary_op)
    actual = dpnp.empty(shape=a.shape, dtype=a.dtype)
    expected = dpnp.empty(shape=a.shape, dtype=a.dtype)

    @dpjit
    def f(a, b):
        return binop(a, b)

    actual = f(a, b)

    expected = binop(a, b)
    np.testing.assert_allclose(
        dpt.asnumpy(actual._array_obj),
        dpt.asnumpy(expected._array_obj),
        rtol=1e-5,
        atol=0,
    )


@pytest.mark.xfail
@pytest.mark.parametrize("filter_str", filter_strings)
def test_unary_ops(filter_str, unary_op, input_arrays):
    a = input_arrays[0]
    uop = getattr(dpnp, unary_op)
    actual = dpnp.empty(shape=a.shape, dtype=a.dtype)
    expected = dpnp.empty(shape=a.shape, dtype=a.dtype)

    @dpjit
    def f(a):
        return uop(a)

    actual = f(a)

    expected = uop(a)
    np.testing.assert_allclose(
        dpt.asnumpy(actual._array_obj),
        dpt.asnumpy(expected._array_obj),
        rtol=1e-5,
        atol=0,
    )
