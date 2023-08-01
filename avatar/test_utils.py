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
from pandora.host_pb2 import Connection
from typing import Tuple
from mobly.asserts import assert_equal  # type: ignore

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
