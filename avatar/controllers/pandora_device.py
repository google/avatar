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
import grpc
import importlib
import asyncio

import mobly.controllers.android_device
import mobly.signals

from ..android_service import ANDROID_SERVER_GRPC_PORT, AndroidService
from ..bumble_server import BumblePandoraServer
from ..utils import Address, into_synchronous


from pandora.host_grpc import Host

MOBLY_CONTROLLER_CONFIG_NAME = 'PandoraDevice'


@into_synchronous()
async def create(configs):
    async def create_device(config):
        module_name = config.pop('module', PandoraDevice.__module__)
        class_name = config.pop('class', PandoraDevice.__name__)

        module = importlib.import_module(module_name)
        device: PandoraDevice = await getattr(module, class_name).create(**config)

        # Always cache the device address after creation,
        # this way it's direclty avaible for `PandoraDeviceLoggerAdapter`
        await device.cache_address()
        return device

    return await asyncio.gather(*[create_device(config) for config in configs])

@into_synchronous()
async def destroy(devices):
    await asyncio.gather(*[device.close() for device in devices])


class PandoraDevice:

    def __init__(self, target):
        self._address = None
        self.channel = grpc.aio.insecure_channel(target)
        self.log = PandoraDeviceLoggerAdapter(logging.getLogger(), self)

    @classmethod
    async def create(cls, **kwargs):
        return cls(**kwargs)

    @property
    def host(self):
        return Host(self.channel)

    @property
    def address(self):
        '''
        Cached bluetooth device address.
        See `Device.cache_address`.
        '''
        assert self._address  # make sure the `address` is already cached
        return self._address

    async def cache_address(self):
        '''
        Read the local address and cache it inside the device object under the `Device.address` property.
        '''
        self._address = Address((await self.host.ReadLocalAddress()).address)

    async def close(self):
        await self.channel.close()


class PandoraDeviceLoggerAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        msg = f'[{self.extra.__class__.__name__}|{self.extra.address}] {msg}'
        return (msg, kwargs)


class AndroidPandoraDevice(PandoraDevice):

    def __init__(self, android_device):
        self.android_device = android_device
        port = ANDROID_SERVER_GRPC_PORT
        self.android_device.services.register('pandora', AndroidService, configs={
            'port': port
        })
        super().__init__(f'localhost:{port}')

    async def close(self):
        super().close()
        mobly.controllers.android_device.destroy([self.android_device])

    @classmethod
    async def create(cls, config):
        android_devices = mobly.controllers.android_device.create(config)
        if not android_devices:
            raise mobly.signals.ControllerError(
                'Expected to get at least 1 android controller objects, got 0.')
        head, *tail = android_devices
        mobly.controllers.android_device.destroy(tail)
        return cls(head)


class BumblePandoraDevice(PandoraDevice):
    def __init__(self, server):
        self.server = server
        self.task = asyncio.create_task(self.server.wait_for_termination())
        super().__init__(f'localhost:{self.server.grpc_port}')

    async def close(self):
        await super().close()
        self.task.cancel()

    @property
    def device(self):
        return self.server.device

    @classmethod
    async def create(cls, transport, **kwargs):
        server = await BumblePandoraServer.open(0, transport, kwargs)
        await server.start()
        return cls(server)
