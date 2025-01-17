# SPDX-FileCopyrightText: 2020 - 2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

from numba.core import ir, types
from numba.core.compiler_machinery import FunctionPass, register_pass
from numba.core.ir_utils import find_topo_order

from numba_dpex.core.exceptions import ComputeFollowsDataInferenceError
from numba_dpex.core.passes.parfor_lowering_pass import ParforLowerFactory
from numba_dpex.core.types.dpnp_ndarray_type import DpnpNdArray

from .parfor import (
    Parfor,
    ParforDiagnostics,
    get_parfor_outputs,
    get_parfor_params,
)


class ParforLegalizeCFDPassImpl:

    """Legalizes the compute-follows-data based device attribute for parfor
    nodes.

    DpnpNdArray array-expressions populate the type of the left-hand-side (LHS)
    of each expression as a default DpnpNdArray instance derived from the
    __array_ufunc__ method of DpnpNdArray class. The pass fixes the LHS type by
    properly applying compute follows data programming model. The pass first
    checks if the right-hand-side (RHS) DpnpNdArray arguments are on the same
    device, else raising a ComputeFollowsDataInferenceError. Once the RHS has
    been validated, the LHS type is updated.

    The pass also updated the usm_type of the LHS based on a USM type
    propagation rule: device > shared > host. Thus, if the usm_type attribute of
    the RHS arrays are "device" and "shared" respectively, the LHS array's
    usm_type attribute will be "device".

    Once the pass has identified a parfor with DpnpNdArrays and legalized it,
    the "lowerer" attribute of the parfor is set to
    ``numba_dpex.core.passes.parfor_lowering_pass._lower_parfor_as_kernel`` so
    that the parfor node is lowered using Dpex's lowerer.

    """

    inputUsmTypeStrToInt = {"device": 3, "shared": 2, "host": 1}
    inputUsmTypeIntToStr = {3: "device", 2: "shared", 1: "host"}

    def __init__(self, state) -> None:
        self._state = state
        self._cfd_updated_values = set()
        self._seen_array_set = set()
        diagnostics = ParforDiagnostics()
        self.nested_fusion_info = diagnostics.nested_fusion_info

    def _check_if_dpnp_empty_call(self, call_stmt, block):
        func_def = block.find_variable_assignment(call_stmt.name)
        if not (
            isinstance(func_def, ir.Assign)
            and isinstance(func_def.value, ir.Expr)
            and func_def.value.op == "getattr"
        ):
            raise AssertionError

        module_name = block.find_variable_assignment(
            func_def.value.list_vars()[0].name
        ).value.value.__name__

        if func_def.value.attr == "empty" and module_name == "dpnp":
            return True
        else:
            return False

    def _check_cfd_parfor_params(self, parfor, checklist):
        deviceTypes = set()
        usmTypes = []

        for para in checklist:
            if not isinstance(self._state.typemap[para], DpnpNdArray):
                continue
            argty = self._state.typemap[para]
            deviceTypes.add(argty.device)
            try:
                usmTypes.append(
                    ParforLegalizeCFDPassImpl.inputUsmTypeStrToInt[
                        argty.usm_type
                    ]
                )
            except KeyError:
                raise ValueError(
                    "Unknown USM type encountered. Supported "
                    "usm types are: device, shared and host."
                )
        # Check compute follows data on the dpnp arrays in checklist
        if len(deviceTypes) > 1:
            raise ComputeFollowsDataInferenceError(
                kernel_name=parfor.loc.short(),
                usmarray_argnum_list=[],
            )
        # Derive the usm_type based on usm allocator precedence rule:
        # device > shared > host
        conforming_usm_ty = max(usmTypes)
        conforming_device_ty = deviceTypes.pop()

        # FIXME: Changed to namedtuple
        return (conforming_usm_ty, conforming_device_ty)

    def _legalize_dpnp_empty_call(self, required_arrty, call_stmt, block):
        args = call_stmt.args
        sigargs = self._state.calltypes[call_stmt].args
        sigargs_new = list(sigargs)
        # Update the RHS usm_type, device, attributes
        for idx, arg in enumerate(args):
            argdef = block.find_variable_assignment(arg.name)
            if argdef:
                attribute = argdef.target.name
                if "usm_type" in attribute:
                    self._state.typemap.update(
                        {attribute: types.literal(required_arrty.usm_type)}
                    )
                    sigargs_new[idx] = types.literal(required_arrty.usm_type)
                elif "device" in attribute:
                    self._state.typemap.update(
                        {attribute: types.literal(required_arrty.device)}
                    )
                    sigargs_new[idx] = types.literal(required_arrty.device)
        sigargs = tuple(sigargs_new)
        new_sig = self._state.typingctx.resolve_function_type(
            self._state.typemap[call_stmt.func.name], sigargs, {}
        )
        self._state.calltypes.update({call_stmt: new_sig})

    def _legalize_array_attrs(
        self, arrattr, legalized_device_ty, legalized_usm_ty
    ):
        modified = False
        updated_device = None
        updated_usm_ty = None

        if self._state.typemap[arrattr].device != legalized_device_ty:
            updated_device = legalized_device_ty
            modified = True

        if self._state.typemap[arrattr].usm_type != legalized_usm_ty:
            updated_usm_ty = legalized_usm_ty
            modified = True

        if modified:
            ty = self._state.typemap[arrattr]
            new_ty = ty.copy(device=updated_device, usm_type=updated_usm_ty)
            self._state.typemap.update({arrattr: new_ty})

        return modified

    def _legalize_parfor_params(self, parfor):
        """Checks the parfor params for compute follows data compliance and
        returns the conforming device for the parfor.

        Args:
            parfor: Parfor node to be analyzed

        Returns:
            str: The device filter string for the parfor if the parfor is
            compute follows data conforming.
        """
        if parfor.params is None:
            return

        outputParams = get_parfor_outputs(parfor, parfor.params)
        checklist = sorted(list(set(parfor.params) - set(outputParams)))

        # Check if any output param was defined outside the parfor
        for para in outputParams:
            if (
                isinstance(self._state.typemap[para], DpnpNdArray)
                and para in self._seen_array_set
            ):
                checklist.append(para)

        # Check params in checklist for CFD compliance and derive the common
        # usm allocator and device based on the checklist params
        usm_ty, device_ty = self._check_cfd_parfor_params(parfor, checklist)

        # Update any outputs that are generated in the parfor
        for para in outputParams:
            if not isinstance(self._state.typemap[para], DpnpNdArray):
                continue
            # Legalize LHS. Skip if we already updated the type before and no
            # further legalization is needed.
            if self._legalize_array_attrs(
                para,
                device_ty,
                ParforLegalizeCFDPassImpl.inputUsmTypeIntToStr[usm_ty],
            ):
                # Keep track of vars that have been updated
                self._cfd_updated_values.add(para)
            else:
                try:
                    self._cfd_updated_values.remove(para)
                except KeyError:
                    pass

        return device_ty

    def _legalize_cfd_parfor_blocks(self, parfor):
        """Legalize the parfor params based on the compute follows data
        programming model and usm allocator precedence rule.
        """
        conforming_device_ty = self._legalize_parfor_params(parfor)

        # Update the parfor's lowerer attribute
        parfor.lowerer = ParforLowerFactory.get_lowerer(conforming_device_ty)

        init_block = parfor.init_block
        blocks = parfor.loop_body

        for stmt in init_block.body:
            self._legalize_stmt(stmt, init_block, inparfor=True)

        for block in blocks.values():
            for stmt in block.body:
                self._legalize_stmt(stmt, block, inparfor=True)

    def _legalize_expr(self, stmt, lhs, lhsty, parent_block, inparfor=False):
        rhs = stmt.value
        if rhs.op == "call":
            if self._check_if_dpnp_empty_call(rhs.func, parent_block):
                if inparfor and lhs in self._cfd_updated_values:
                    self._legalize_dpnp_empty_call(lhsty, rhs, parent_block)
                self._seen_array_set.add(lhs)
            # TODO: If any other array constructor that does not take
            # args, just add to self._seen_array_set
            else:
                for ele in rhs.list_vars():
                    if ele.name in self._cfd_updated_values:
                        # TODO: Resolve function type with new argument
                        raise NotImplementedError(
                            "Compute follows data is not currently "
                            "supported for function calls."
                        )
        elif rhs.op == "cast" and rhs.value.name in self._cfd_updated_values:
            device_ty = self._state.typemap[rhs.value.name].device
            usm_ty = self._state.typemap[rhs.value.name].usm_type
            if self._legalize_array_attrs(
                arrattr=lhs,
                legalized_device_ty=device_ty,
                legalized_usm_ty=usm_ty,
            ):
                self._cfd_updated_values.add(lhs)
            else:
                try:
                    self._cfd_updated_values.remove(lhs)
                except KeyError:
                    pass
        else:
            # The assumption is all other expr types are by now either parfors
            # or are insts like setattr, getattr,  # getitem, etc. and do not
            # need CFD legalization.
            self._seen_array_set.add(lhs)

    def _legalize_stmt(self, stmt, parent_block, inparfor=False):
        if isinstance(stmt, ir.Assign):
            lhs = stmt.target.name
            lhsty = self._state.typemap[lhs]
            if isinstance(lhsty, DpnpNdArray):
                if isinstance(stmt.value, ir.Arg):
                    self._seen_array_set.add(lhs)
                elif isinstance(stmt.value, ir.Expr):
                    self._legalize_expr(
                        stmt, lhs, lhsty, parent_block, inparfor
                    )
        elif isinstance(stmt, Parfor):
            self._legalize_cfd_parfor_blocks(stmt)
        elif isinstance(stmt, ir.Return):
            # Check if the return value is a DpnpNdArray and was changed by
            # compute follows data legalization
            retty = self._state.typemap[stmt.value.name]
            if (
                isinstance(retty, DpnpNdArray)
                and stmt.value.name in self._cfd_updated_values
                and self._state.return_type != retty
            ):
                self._state.return_type = retty

    def run(self):
        # The get_parfor_params needs to be run here to initialize the parfor
        # nodes prior to using them.
        _, _ = get_parfor_params(
            self._state.func_ir.blocks,
            self._state.flags.auto_parallel,
            self.nested_fusion_info,
        )

        # FIXME: Traversing the blocks in  topological order is not sufficient.
        # The traversal should be converted to a backward data flow traversal of
        # the CFG. The algorithm needs to then become a fixed-point work list
        # algorithm.
        topo_order = find_topo_order(self._state.func_ir.blocks)

        # Apply CFD legalization to parfor nodes and dpnp_empty calls
        for label in topo_order:
            block = self._state.func_ir.blocks[label]
            for stmt in block.body:
                self._legalize_stmt(stmt, block)


@register_pass(mutates_CFG=True, analysis_only=False)
class ParforLegalizeCFDPass(FunctionPass):
    _name = "parfor_Legalize_CFD_pass"

    def __init__(self):
        FunctionPass.__init__(self)

    def run_pass(self, state):
        """
        Legalize CFD of parfor nodes.
        """
        # Ensure we have an IR and type information.
        assert state.func_ir
        cfd_legalizer = ParforLegalizeCFDPassImpl(state)
        cfd_legalizer.run()

        return True
