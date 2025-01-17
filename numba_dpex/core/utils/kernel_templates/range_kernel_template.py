# SPDX-FileCopyrightText: 2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import sys

import dpnp
from numba.core import compiler

import numba_dpex as dpex


class RangeKernelTemplate:
    """A template class to generate a numba_dpex.kernel decorated function
    representing a basic range kernel.
    """

    def __init__(
        self,
        kernel_name,
        kernel_params,
        kernel_rank,
        ivar_names,
        sentinel_name,
        loop_ranges,
        param_dict,
    ) -> None:
        """Creates a new RangeKernelTemplate instance and stores the stub
        string and the Numba typed IR for the kernel function.

        Args:
            kernel_name (str): The name of the kernel function
            kernel_params (list): A list of names of the kernel arguments
            kernel_rank (int): The dimensionality of the range.
            ivar_names (list): A list of the index variables generated by Numba
            for every kernel range dimension.
            sentinel_name (str): A textual marker inserted into the kernel
            function to help Numba identify where to transform the stub
            kernel's IR.
            loop_ranges (list): The start, stop and step information of each
            range dimension.
            param_dict (dict): Dictionary to lookup variable names for loop
            range attributes.
        """
        self._kernel_name = kernel_name
        self._kernel_params = kernel_params
        self._kernel_rank = kernel_rank
        self._ivar_names = ivar_names
        self._sentinel_name = sentinel_name
        self._loop_ranges = loop_ranges
        self._param_dict = param_dict

        self._kernel_txt = self._generate_kernel_stub_as_string()
        self._kernel_ir = self._generate_kernel_ir()

    def _generate_kernel_stub_as_string(self):
        """Generates a stub dpex kernel for the parfor as a string.

        Returns:
            str: A string representing a stub kernel function for the parfor.
        """
        kernel_txt = ""

        # Create the dpex kernel function.
        kernel_txt += "def " + self._kernel_name
        kernel_txt += "(" + (", ".join(self._kernel_params)) + "):\n"
        global_id_dim = 0
        for_loop_dim = self._kernel_rank
        global_id_dim = self._kernel_rank

        for dim in range(global_id_dim):
            dimstr = str(dim)
            kernel_txt += (
                f"    {self._ivar_names[dim]} = dpex.get_global_id({dimstr})\n"
            )

        for dim in range(global_id_dim, for_loop_dim):
            for indent in range(1 + (dim - global_id_dim)):
                kernel_txt += "    "

            start, stop, step = self._loop_ranges[dim]
            st = str(self._param_dict.get(str(start), start))
            en = str(self._param_dict.get(str(stop), stop))
            kernel_txt += (
                f"for {self._ivar_names[dim]} in range({st}, {en} + 1):\n"
            )

        for dim in range(global_id_dim, for_loop_dim):
            for _ in range(1 + (dim - global_id_dim)):
                kernel_txt += "    "

        # Add the sentinel assignment so that we can find the loop body position
        # in the IR.
        kernel_txt += "    "
        kernel_txt += self._sentinel_name + " = 0\n"

        # A kernel function does not return anything
        kernel_txt += "    return None\n"

        return kernel_txt

    def _generate_kernel_ir(self):
        """Exec the kernel_txt string into a Python function object and then
        compile it using Numba's compiler front end.

        Returns: The Numba functionIR object for the compiled kernel_txt string.

        """
        globls = {"dpnp": dpnp, "dpex": dpex}
        locls = {}
        exec(self._kernel_txt, globls, locls)
        kernel_fn = locls[self._kernel_name]

        return compiler.run_frontend(kernel_fn)

    @property
    def kernel_ir(self):
        """Returns the Numba IR generated for a RangeKernelTemplate.

        Returns: The Numba functionIR object for the compiled kernel_txt string.
        """
        return self._kernel_ir

    @property
    def kernel_string(self):
        """Returns the function string generated for a RangeKernelTemplate.

        Returns:
            str: A string representing a stub kernel function for the parfor.
        """
        return self._kernel_txt

    def dump_kernel_string(self):
        """Helper to print the kernel function string."""
        print(self._kernel_txt)
        sys.stdout.flush()

    def dump_kernel_ir(self):
        """Helper to dump the Numba IR for the RangeKernelTemplate."""
        self._kernel_ir.dump()
