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

from avatar import PandoraDevice
from mobly.asserts import assert_equal  # type: ignore
from mobly.asserts import assert_is_not_none  # type: ignore
from pandora.host_pb2 import RANDOM
from pandora.host_pb2 import Connection
from pandora.host_pb2 import DataTypes
from pandora.host_pb2 import OwnAddressType
from typing import Tuple


# Make classic connection task.
async def make_bredr_connection(initiator: PandoraDevice, acceptor: PandoraDevice) -> Tuple[Connection, Connection]:
    init_res, wait_res = await asyncio.gather(
        initiator.aio.host.Connect(address=acceptor.address),
        acceptor.aio.host.WaitConnection(address=initiator.address),
    )
    assert_equal(init_res.result_variant(), 'connection')
    assert_equal(wait_res.result_variant(), 'connection')
    assert init_res.connection is not None and wait_res.connection is not None
    return init_res.connection, wait_res.connection


# Make LE connection task.
async def make_le_connection(
    central: PandoraDevice,
    peripheral: PandoraDevice,
    central_address_type: OwnAddressType = RANDOM,
    peripheral_address_type: OwnAddressType = RANDOM,
) -> Tuple[Connection, Connection]:
    advertise = peripheral.aio.host.Advertise(
        legacy=True,
        connectable=True,
        own_address_type=peripheral_address_type,
        data=DataTypes(manufacturer_specific_data=b'pause cafe'),
    )

    scan = central.aio.host.Scan(own_address_type=central_address_type)
    ref = await anext((x async for x in scan if x.data.manufacturer_specific_data == b'pause cafe'))
    scan.cancel()

    adv_res, conn_res = await asyncio.gather(
        anext(aiter(advertise)),
        central.aio.host.ConnectLE(**ref.address_asdict(), own_address_type=central_address_type),
    )
    assert_equal(conn_res.result_variant(), 'connection')
    cen_per, per_cen = conn_res.connection, adv_res.connection
    assert_is_not_none(cen_per)
    assert_is_not_none(per_cen)
    assert cen_per, per_cen
    advertise.cancel()
    return cen_per, per_cen
