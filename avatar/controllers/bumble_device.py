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


""" Bumble Device Mobly Controller"""

import asyncio
import os
import random
import sys
import traceback

from bumble.device import Device, DeviceConfiguration
from bumble.host import Host
from bumble import transport
from bumble.sdp import (
    DataElement, ServiceAttribute,
    SDP_SERVICE_RECORD_HANDLE_ATTRIBUTE_ID,
    SDP_SERVICE_CLASS_ID_LIST_ATTRIBUTE_ID,
    SDP_PROTOCOL_DESCRIPTOR_LIST_ATTRIBUTE_ID,
    SDP_BLUETOOTH_PROFILE_DESCRIPTOR_LIST_ATTRIBUTE_ID
)
from bumble.core import (
    BT_GENERIC_AUDIO_SERVICE, BT_HANDSFREE_SERVICE,
    BT_L2CAP_PROTOCOL_ID, BT_RFCOMM_PROTOCOL_ID
)

import avatar

MOBLY_CONTROLLER_CONFIG_NAME = 'BumbleDevice'


# Run `create` asynchronously in our loop so Bumble(s) IO and gRPC servers
# are created into it.
# Also permit to `create` devices in parallel.
def create(configs):
    devices: list(BumbleDevice) = [BumbleDevice(config) for config in configs]

    async def coro():
        return await asyncio.gather(*[device.open() for device in devices])

    return avatar.run_until_complete(coro())


# Destroy devices in parallel.
def destroy(devices):
    async def coro():
        return await asyncio.gather(*[device.close() for device in devices])

    return avatar.run_until_complete(coro())


class BumbleDevice:
    # device configuration
    _config = []

    # hci transport instance
    _hci = None

    # device instance
    _device: Device = None

    # io capability name
    _io_capability_name: str = None

    def __init__(self, config):
        self._config = config

    async def open(self):
        try:
            self._hci = await transport.open_transport(
                self._config.get('transport', '')
            )
        except:
            print(traceback.format_exc(), end='', file=sys.stderr)
            os._exit(1)

        # generate a random address
        self._random_address = (  # address is static random
            f'{random.randint(192,255):02X}'
        )
        for c in random.sample(range(255), 5):
            self._random_address += f':{c:02X}'

        # initialize bumble device
        device_config = DeviceConfiguration()
        device_config.load_from_dict(self._config)
        host = Host(
            controller_source=self._hci.source, controller_sink=self._hci.sink
        )
        self._device = Device(
            config=device_config, host=host, address=self._random_address
        )

        # FIXME: add `classic_enabled` to `DeviceConfiguration` ?
        self.device.classic_enabled = self._config.get('classic_enabled', False)
        # Add fake a2dp service to avoid Android disconnect (TODO: remove when a2dp is supported)
        self.device.sdp_service_records = self.__make_sdp_records(1)
        self._io_capability_name = self._config.get(
            'io_capability', 'no_output_no_input'
        ).upper()

        # start bumble device
        await self._device.power_on()
        return self

    async def close(self):
        await self.device.host.flush()
        await self._hci.close()
        self._device = None
        self._hci = None

    async def reset(self):
        await self.close()
        await self.open()

    @property
    def device(self):
        return self._device

    @property
    def io_capability_name(self):
        return self._io_capability_name

    @property
    def random_address(self):
        return self._random_address

    def __make_sdp_records(self, rfcomm_channel):
        return {
            0x00010001: [
                ServiceAttribute(SDP_SERVICE_RECORD_HANDLE_ATTRIBUTE_ID,
                                 DataElement.unsigned_integer_32(0x00010001)),
                ServiceAttribute(
                    SDP_SERVICE_CLASS_ID_LIST_ATTRIBUTE_ID,
                    DataElement.sequence([
                        DataElement.uuid(BT_HANDSFREE_SERVICE),
                        DataElement.uuid(BT_GENERIC_AUDIO_SERVICE)
                    ])),
                ServiceAttribute(
                    SDP_PROTOCOL_DESCRIPTOR_LIST_ATTRIBUTE_ID,
                    DataElement.sequence([
                        DataElement.sequence(
                            [DataElement.uuid(BT_L2CAP_PROTOCOL_ID)]),
                        DataElement.sequence([
                            DataElement.uuid(BT_RFCOMM_PROTOCOL_ID),
                            DataElement.unsigned_integer_8(rfcomm_channel)
                        ])
                    ])),
                ServiceAttribute(
                    SDP_BLUETOOTH_PROFILE_DESCRIPTOR_LIST_ATTRIBUTE_ID,
                    DataElement.sequence([
                        DataElement.sequence([
                            DataElement.uuid(BT_HANDSFREE_SERVICE),
                            DataElement.unsigned_integer_16(0x0105)
                        ])
                    ]))
            ]
        }
