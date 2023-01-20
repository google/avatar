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
import contextlib
import logging
from typing import Any, MutableMapping, Optional, Tuple, Union

import grpc

import avatar
from avatar import utils

from pandora.host_grpc import Host
from pandora.security_grpc import Security, SecurityStorage
from pandora.asha_grpc import ASHA


class PandoraClient:
    """Provides Pandora interface access to a device via gRPC."""

    def __init__(self, target: str, device: Optional[Any] = None) -> None:
        """Creates a PandoraClient.

        Establishes a channel with the Pandora gRPC server.

        Args:
          target: Server address for the gRPC channel.
          device: Mobly controller instance associated with this client.
        """
        self._address = utils.Address(b'\x00\x00\x00\x00\x00\x00')
        self._target = target
        self._channel = grpc.insecure_channel(target)
        self._aio_channel = None
        self._device = device
        self._log = PandoraClientLoggerAdapter(logging.getLogger(), {'obj': self})

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
                    self._aio_channel = grpc.aio.insecure_channel(self._target)
                return self._aio_channel
        return self._channel

    @property
    def address(self) -> utils.Address:
        """Returns the BT address."""
        return self._address

    @address.setter
    def address(self, address: Union[bytes, str]) -> None:
        """Sets the BT address."""
        self._address = utils.Address(address)

    @property
    def device(self) -> Optional[Any]:
        """Returns the Mobly device associated with this client, if specified."""
        return self._device

    @property
    def log(self) -> logging.LoggerAdapter:
        """Returns the logger associated with this client."""
        return self._log

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
        obj = self.extra['obj']
        # pytype: disable=attribute-error
        msg = f'[{obj.__class__.__name__}|{obj.address}] {msg}'
        # pytype: enable=attribute-error
        return (msg, kwargs)
