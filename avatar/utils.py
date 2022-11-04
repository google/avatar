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


class Address(bytes):

    def __new__(cls, address):
        if type(address) is bytes:
            address_bytes = address
        elif type(address) is str:
            address_bytes = bytes.fromhex(address.replace(':', ''))
        else:
            raise ValueError('Invalid address format')

        if len(address_bytes) != 6:
            raise ValueError('Invalid address length')

        return bytes.__new__(cls, address_bytes)

    def __str__(self):
        return ':'.join([f'{x:02X}' for x in self])
