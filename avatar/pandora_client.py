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


"""Pandora client interface for Avatar tests."""

import asyncio
import avatar
import bumble
import contextlib
import grpc
import logging

from typing import Any, MutableMapping, Optional, Tuple, Union

from avatar import utils
from avatar.bumble_device import BumbleDevice

from bumble.hci import Address as BumbleAddress

from pandora.host_grpc import Host
from pandora.security_grpc import Security, SecurityStorage
from pandora.asha_grpc import ASHA


class PandoraClient:
    """Provides Pandora interface access to a device via gRPC."""

    # public fields
    grpc_target: str  # Server address for the gRPC channel.
    log: 'PandoraClientLoggerAdapter'  # Logger adapter.

    # private fields
    _address: utils.Address  # Bluetooth device address
    _channel: grpc.Channel  # Synchronous gRPC channel.
    _aio_channel: Optional[grpc.aio.Channel]  # Asynchronous gRPC channel.

    def __init__(self, grpc_target: str) -> None:
        """Creates a PandoraClient.

        Establishes a channel with the Pandora gRPC server.

        Args:
          grpc_target: Server address for the gRPC channel.
        """
        self.grpc_target = grpc_target
        self.log = PandoraClientLoggerAdapter(logging.getLogger(), {'obj': self})
        self._address = utils.Address(b'\x00\x00\x00\x00\x00\x00')
        self._channel = grpc.insecure_channel(grpc_target)
        self._aio_channel = None

    def close(self) -> None:
        """Closes the gRPC channels."""
        self._channel.close()
        if self._aio_channel:
            avatar.run_until_complete(self._aio_channel.close())

    @property
    def channel(self) -> Union[grpc.Channel, grpc.aio.Channel]:
        """Returns the active gRPC channel."""
        # Force the use of the asynchronous channel when running in our event loop.
        with contextlib.suppress(RuntimeError):
            if asyncio.get_running_loop() == avatar.loop:
                if not self._aio_channel:
                    self._aio_channel = grpc.aio.insecure_channel(self.grpc_target)
                return self._aio_channel
        return self._channel

    @property
    def address(self) -> utils.Address:
        """Returns the BD address."""
        return self._address

    @address.setter
    def address(self, address: Union[bytes, str, BumbleAddress]) -> None:
        """Sets the BD address."""
        self._address = utils.Address(address)

    # Pandora interfaces

    @property
    def host(self) -> Host:
        """Returns the Pandora Host gRPC interface."""
        return Host(self.channel)

    @property
    def security(self) -> Security:
        """Returns the Pandora Security gRPC interface."""
        return Security(self.channel)

    @property
    def security_storage(self) -> SecurityStorage:
        """Returns the Pandora SecurityStorage gRPC interface."""
        return SecurityStorage(self.channel)

    @property
    def asha(self) -> ASHA:
        """Returns the Pandora ASHA gRPC interface."""
        return ASHA(self.channel)


class PandoraClientLoggerAdapter(logging.LoggerAdapter):
    """Formats logs from the PandoraClient."""

    def process(
        self, msg: str, kwargs: MutableMapping[str, Any]
    ) -> Tuple[str, MutableMapping[str, Any]]:
        assert self.extra
        obj = self.extra['obj']
        assert isinstance(obj, PandoraClient)
        msg = f'[{obj.__class__.__name__}|{obj.address}] {msg}'
        return (msg, kwargs)


class BumblePandoraClient(PandoraClient):
    """Special Pandora client which also give access to a Bumble device instance."""

    _bumble: BumbleDevice  # Bumble device wrapper.

    def __init__(self, grpc_target: str, bumble: BumbleDevice) -> None:
        self._bumble = bumble
        super().__init__(grpc_target)

    @property
    def device(self) -> bumble.device.Device:
        return self._bumble.device

    @property
    def random_address(self) -> utils.Address:
        return utils.Address(self.device.random_address)
