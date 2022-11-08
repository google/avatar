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
import avatar
import contextlib

import mobly.controllers.android_device
import mobly.signals

from ..android_service import ANDROID_SERVER_GRPC_PORT, AndroidService
from ..bumble_server import BumblePandoraServer
from ..utils import Address


from pandora.host_grpc import Host

MOBLY_CONTROLLER_CONFIG_NAME = 'PandoraDevice'


def create_device(config):
    module_name = config.pop('module', PandoraDevice.__module__)
    class_name = config.pop('class', PandoraDevice.__name__)

    module = importlib.import_module(module_name)
    return getattr(module, class_name).create(**config)

# Run `create` asynchronously in our loop so Bumble(s) IO and gRPC servers
# are created into it.
# Also permit to `create` devices in parallel.
def create(configs):
    async def coro(): return await asyncio.gather(*[create_device(config) for config in configs])
    return asyncio.run_coroutine_threadsafe(coro(), avatar.loop).result()

# Destroy devices in parallel.
def destroy(devices):
    async def coro(): return await asyncio.gather(*[device.close() for device in devices])
    return asyncio.run_coroutine_threadsafe(coro(), avatar.loop).result()


class PandoraDevice:

    def __init__(self, target):
        self.address = Address(b'\x00\x00\x00\x00\x00\x00')
        self.channels = (grpc.insecure_channel(target), grpc.aio.insecure_channel(target))
        self.log = PandoraDeviceLoggerAdapter(logging.getLogger(), self)

    @classmethod
    async def create(cls, **kwargs):
        return cls(**kwargs)

    async def close(self):
        self.channels[0].close()
        await self.channels[1].close()

    @property
    def channel(self):
        # Force the use of the asynchronous channel when running in our event loop.
        with contextlib.suppress(RuntimeError):
            if avatar.loop == asyncio.get_running_loop(): return self.channels[1]
        return self.channels[0]

    @property
    def host(self) -> Host:
        return Host(self.channel)


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
        await super().close()
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
        self.server: BumblePandoraServer = server
        super().__init__(f'localhost:{self.server.grpc_port}')

    async def close(self):
        await self.server.close()
        await super().close()

    @property
    def device(self):
        return self.server.device

    @classmethod
    async def create(cls, transport, **kwargs):
        server = await BumblePandoraServer.open(0, transport, kwargs)
        await server.start()
        return cls(server)
