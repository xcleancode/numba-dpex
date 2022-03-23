# Copyright 2021 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from numba.core.datamodel.models import ArrayModel
from numba.extending import register_model

from numba_dppy import target as dppy_target

from .dpctl_types import UsmSharedArrayType

# This tells Numba to use the default Numpy ndarray data layout for
# object of type UsmArray.
# register_model(UsmSharedArrayType)(DPPYArrayModel)
register_model(UsmSharedArrayType)(ArrayModel)
# dppy_target.spirv_data_model_manager.register(UsmSharedArrayType, DPPYArrayModel)
dppy_target.spirv_data_model_manager.register(UsmSharedArrayType, ArrayModel)
