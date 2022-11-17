# Copyright 2022 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from bumble.hci import Address


ADDRESS_TYPES = {
    "public": Address.PUBLIC_DEVICE_ADDRESS,
    "random": Address.RANDOM_DEVICE_ADDRESS,
    "public_identity": Address.PUBLIC_IDENTITY_ADDRESS,
    "random_static_identity": Address.RANDOM_IDENTITY_ADDRESS
}

def address_from_request(request, field):
    return Address(bytes(reversed(getattr(request, field))), ADDRESS_TYPES[field])