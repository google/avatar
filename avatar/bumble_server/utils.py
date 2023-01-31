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

import logging

from bumble.device import Device
from bumble.hci import Address
from google.protobuf.message import Message
from typing import Any, MutableMapping, Optional, Tuple

ADDRESS_TYPES: dict[str, int] = {
    "public": Address.PUBLIC_DEVICE_ADDRESS,
    "random": Address.RANDOM_DEVICE_ADDRESS,
    "public_identity": Address.PUBLIC_IDENTITY_ADDRESS,
    "random_static_identity": Address.RANDOM_IDENTITY_ADDRESS,
}


def address_from_request(request: Message, field: Optional[str]) -> Address:
    if field is None:
        return Address.ANY
    return Address(bytes(reversed(getattr(request, field))), ADDRESS_TYPES[field])


class BumbleServerLoggerAdapter(logging.LoggerAdapter):  # type: ignore
    """Formats logs from the PandoraClient."""

    def process(self, msg: str, kwargs: MutableMapping[str, Any]) -> Tuple[str, MutableMapping[str, Any]]:
        assert self.extra
        service_name = self.extra['service_name']
        assert isinstance(service_name, str)
        device = self.extra['device']
        assert isinstance(device, Device)
        addr_bytes = bytes(reversed(bytes(device.public_address)))
        addr = ':'.join([f'{x:02X}' for x in addr_bytes[4:]])
        return (f'[bumble.{service_name}:{addr}] {msg}', kwargs)
