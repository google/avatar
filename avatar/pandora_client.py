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

import avatar.aio
import bumble
import bumble.device
import grpc
import grpc.aio
import logging

from avatar.bumble_device import BumbleDevice
from bumble.hci import Address as BumbleAddress
from dataclasses import dataclass
from pandora import asha_grpc, asha_grpc_aio, host_grpc, host_grpc_aio, security_grpc, security_grpc_aio
from typing import Any, MutableMapping, Optional, Tuple, Union


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
    grpc_target: str  # Server address for the gRPC channel.
    log: 'PandoraClientLoggerAdapter'  # Logger adapter.
    channel: grpc.Channel  # Synchronous gRPC channel.

    # private fields
    _address: Address  # Bluetooth device address
    _aio: Optional['PandoraClient.Aio']  # Asynchronous gRPC channel.

    def __init__(self, grpc_target: str, name: str = '..') -> None:
        """Creates a PandoraClient.

        Establishes a channel with the Pandora gRPC server.

        Args:
          grpc_target: Server address for the gRPC channel.
        """
        self.grpc_target = grpc_target
        self.log = PandoraClientLoggerAdapter(logging.getLogger(), {'client': self, 'client_name': name})
        self.channel = grpc.insecure_channel(grpc_target)  # type: ignore
        self._address = Address(b'\x00\x00\x00\x00\x00\x00')
        self._aio = None

    def close(self) -> None:
        """Closes the gRPC channels."""
        self.channel.close()
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
        await self.aio.host.FactoryReset()
        for _ in range(0, 3):
            try:
                self._address = Address((await self.aio.host.ReadLocalAddress(wait_for_ready=True)).address)
                return
            except grpc.RpcError as e:
                assert e.code() == grpc.StatusCode.UNAVAILABLE  # type: ignore
        raise RuntimeError('unable to establish a new connection after a `FactoryReset`')

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

    @property
    def asha(self) -> asha_grpc.ASHA:
        """Returns the Pandora ASHA gRPC interface."""
        return asha_grpc.ASHA(self.channel)

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
        def asha(self) -> asha_grpc_aio.ASHA:
            """Returns the Pandora ASHA gRPC interface."""
            return asha_grpc_aio.ASHA(self.channel)

    @property
    def aio(self) -> 'PandoraClient.Aio':
        if not self._aio:
            self._aio = PandoraClient.Aio(grpc.aio.insecure_channel(self.grpc_target))
        return self._aio


class PandoraClientLoggerAdapter(logging.LoggerAdapter):  # type: ignore
    """Formats logs from the PandoraClient."""

    def process(self, msg: str, kwargs: MutableMapping[str, Any]) -> Tuple[str, MutableMapping[str, Any]]:
        assert self.extra
        client = self.extra['client']
        assert isinstance(client, PandoraClient)
        client_name = self.extra.get('client_name', client.__class__.__name__)
        addr = ':'.join([f'{x:02X}' for x in client.address[4:]])
        return (f'[{client_name}:{addr}] {msg}', kwargs)


class BumblePandoraClient(PandoraClient):
    """Special Pandora client which also give access to a Bumble device instance."""

    _bumble: BumbleDevice  # Bumble device wrapper.

    def __init__(self, grpc_target: str, bumble: BumbleDevice) -> None:
        super().__init__(grpc_target, 'bumble')
        self._bumble = bumble

    @property
    def device(self) -> bumble.device.Device:
        return self._bumble.device

    @property
    def random_address(self) -> Address:
        return Address(self.device.random_address)