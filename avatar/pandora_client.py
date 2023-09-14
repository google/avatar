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
import avatar.aio
import bumble
import bumble.device
import grpc
import grpc.aio
import logging

from avatar.metrics.interceptors import aio_interceptors
from avatar.metrics.interceptors import interceptors
from bumble import pandora as bumble_server
from bumble.hci import Address as BumbleAddress
from bumble.pandora.device import PandoraDevice as BumblePandoraDevice
from dataclasses import dataclass
from pandora import host_grpc
from pandora import host_grpc_aio
from pandora import security_grpc
from pandora import security_grpc_aio
from typing import Any, Dict, MutableMapping, Optional, Tuple, Union


class Address(bytes):
    def __new__(cls, address: Union[bytes, str, BumbleAddress]) -> 'Address':
        if type(address) is bytes:
            address_bytes = address
        elif type(address) is str:
            address_bytes = bytes.fromhex(address.replace(':', ''))
        elif isinstance(address, BumbleAddress):
            address_bytes = bytes(reversed(bytes(address)))
        else:
            raise ValueError('Invalid address format')

        if len(address_bytes) != 6:
            raise ValueError('Invalid address length')

        return bytes.__new__(cls, address_bytes)

    def __str__(self) -> str:
        return ':'.join([f'{x:02X}' for x in self])


class PandoraClient:
    """Provides Pandora interface access to a device via gRPC."""

    # public fields
    name: str
    grpc_target: str  # Server address for the gRPC channel.
    log: 'PandoraClientLoggerAdapter'  # Logger adapter.

    # private fields
    _channel: grpc.Channel  # Synchronous gRPC channel.
    _address: Address  # Bluetooth device address
    _aio: Optional['PandoraClient.Aio']  # Asynchronous gRPC channel.

    def __init__(self, grpc_target: str, name: str = '..') -> None:
        """Creates a PandoraClient.

        Establishes a channel with the Pandora gRPC server.

        Args:
          grpc_target: Server address for the gRPC channel.
        """
        self.name = name
        self.grpc_target = grpc_target
        self.log = PandoraClientLoggerAdapter(logging.getLogger(), {'client': self})
        self._channel = grpc.intercept_channel(grpc.insecure_channel(grpc_target), *interceptors(self))  # type: ignore
        self._address = Address(b'\x00\x00\x00\x00\x00\x00')
        self._aio = None

    def close(self) -> None:
        """Closes the gRPC channels."""
        self._channel.close()
        if self._aio:
            avatar.aio.run_until_complete(self._aio.channel.close())

    @property
    def address(self) -> Address:
        """Returns the BD address."""
        return self._address

    @address.setter
    def address(self, address: Union[bytes, str, BumbleAddress]) -> None:
        """Sets the BD address."""
        self._address = Address(address)

    async def reset(self) -> None:
        """Factory reset the device & read it's BD address."""
        attempts, max_attempts = 1, 3
        while True:
            try:
                await self.aio.host.FactoryReset(wait_for_ready=True, timeout=15.0)

                # Factory reset stopped the server, close the client too.
                assert self._aio
                await self._aio.channel.close()
                self._aio = None

                # This call might fail if the server is unavailable.
                self._address = Address(
                    (await self.aio.host.ReadLocalAddress(wait_for_ready=True, timeout=15.0)).address
                )
                return
            except grpc.aio.AioRpcError as e:
                if e.code() in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED):
                    if attempts <= max_attempts:
                        self.log.debug(f'Server unavailable, retry [{attempts}/{max_attempts}].')
                        attempts += 1
                        continue
                    self.log.exception(f'Server still unavailable after {attempts} attempts, abort.')
                raise e

    @property
    def channel(self) -> grpc.Channel:
        """Returns the synchronous gRPC channel."""
        try:
            _ = asyncio.get_running_loop()
        except:
            return self._channel
        raise RuntimeError('Trying to use the synchronous gRPC channel from asynchronous code.')

    # Pandora interfaces

    @property
    def host(self) -> host_grpc.Host:
        """Returns the Pandora Host gRPC interface."""
        return host_grpc.Host(self.channel)

    @property
    def security(self) -> security_grpc.Security:
        """Returns the Pandora Security gRPC interface."""
        return security_grpc.Security(self.channel)

    @property
    def security_storage(self) -> security_grpc.SecurityStorage:
        """Returns the Pandora SecurityStorage gRPC interface."""
        return security_grpc.SecurityStorage(self.channel)

    @dataclass
    class Aio:
        channel: grpc.aio.Channel

        @property
        def host(self) -> host_grpc_aio.Host:
            """Returns the Pandora Host gRPC interface."""
            return host_grpc_aio.Host(self.channel)

        @property
        def security(self) -> security_grpc_aio.Security:
            """Returns the Pandora Security gRPC interface."""
            return security_grpc_aio.Security(self.channel)

        @property
        def security_storage(self) -> security_grpc_aio.SecurityStorage:
            """Returns the Pandora SecurityStorage gRPC interface."""
            return security_grpc_aio.SecurityStorage(self.channel)

    @property
    def aio(self) -> 'PandoraClient.Aio':
        if not self._aio:
            self._aio = PandoraClient.Aio(
                grpc.aio.insecure_channel(self.grpc_target, interceptors=aio_interceptors(self))
            )
        return self._aio


class PandoraClientLoggerAdapter(logging.LoggerAdapter):  # type: ignore
    """Formats logs from the PandoraClient."""

    def process(self, msg: str, kwargs: MutableMapping[str, Any]) -> Tuple[str, MutableMapping[str, Any]]:
        assert self.extra
        client = self.extra['client']
        assert isinstance(client, PandoraClient)
        addr = ':'.join([f'{x:02X}' for x in client.address[4:]])
        return (f'[{client.name:<8}:{addr}] {msg}', kwargs)


class BumblePandoraClient(PandoraClient):
    """Special Pandora client which also give access to a Bumble device instance."""

    _bumble: BumblePandoraDevice  # Bumble device wrapper.
    _server_config: bumble_server.Config  # Bumble server config.

    def __init__(self, grpc_target: str, bumble: BumblePandoraDevice, server_config: bumble_server.Config) -> None:
        super().__init__(grpc_target, 'bumble')
        self._bumble = bumble
        self._server_config = server_config

    @property
    def server_config(self) -> bumble_server.Config:
        return self._server_config

    @property
    def config(self) -> Dict[str, Any]:
        return self._bumble.config

    @property
    def device(self) -> bumble.device.Device:
        return self._bumble.device

    @property
    def random_address(self) -> Address:
        return Address(self.device.random_address)
