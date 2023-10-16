# Copyright 2023 Google LLC
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

import asyncio

from avatar import BumblePandoraDevice
from avatar import PandoraDevice
from bumble.device import Connection as BumbleConnection
from mobly.asserts import assert_equal  # type: ignore
from mobly.asserts import assert_is_not_none  # type: ignore
from pandora._utils import AioStream
from pandora.host_pb2 import AdvertiseResponse
from pandora.host_pb2 import Connection
from pandora.host_pb2 import OwnAddressType
from pandora.host_pb2 import ScanningResponse
from typing import Optional, Tuple


def get_raw_connection_handle(device: PandoraDevice, connection: Connection) -> int:
    assert isinstance(device, BumblePandoraDevice)
    return int.from_bytes(connection.cookie.value, 'big')


def get_raw_connection(device: PandoraDevice, connection: Connection) -> Optional[BumbleConnection]:
    assert isinstance(device, BumblePandoraDevice)
    return device.device.lookup_connection(get_raw_connection_handle(device, connection))


async def connect(initiator: PandoraDevice, acceptor: PandoraDevice) -> Tuple[Connection, Connection]:
    init_res, wait_res = await asyncio.gather(
        initiator.aio.host.Connect(address=acceptor.address),
        acceptor.aio.host.WaitConnection(address=initiator.address),
    )
    assert_equal(init_res.result_variant(), 'connection')
    assert_equal(wait_res.result_variant(), 'connection')
    assert init_res.connection is not None and wait_res.connection is not None
    return init_res.connection, wait_res.connection


async def connect_le(
    initiator: PandoraDevice,
    acceptor: AioStream[AdvertiseResponse],
    scan: ScanningResponse,
    own_address_type: OwnAddressType,
    cancel_advertisement: bool = True,
) -> Tuple[Connection, Connection]:
    (init_res, wait_res) = await asyncio.gather(
        initiator.aio.host.ConnectLE(own_address_type=own_address_type, **scan.address_asdict()),
        anext(aiter(acceptor)),  # pytype: disable=name-error
    )
    if cancel_advertisement:
        acceptor.cancel()
    assert_equal(init_res.result_variant(), 'connection')
    assert_is_not_none(init_res.connection)
    assert init_res.connection
    return init_res.connection, wait_res.connection
