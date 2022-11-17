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

import asyncio
import logging

from contextlib import suppress
from typing import AsyncIterator, Optional

from avatar.bumble_server.utils import address_from_request

from bumble.core import BT_LE_TRANSPORT
from bumble.hci import Address
from bumble.device import Connection as BumbleConnection, Device
from bumble.smp import PairingConfig, PairingDelegate as BasePairingDelegate

from google.protobuf.any_pb2 import Any
from google.protobuf.empty_pb2 import Empty
from google.protobuf.wrappers_pb2 import BoolValue

from pandora.host_pb2 import Connection

from pandora.security_grpc import SecurityServicer
from pandora.security_pb2 import (
    PairingEvent, PairingEventAnswer
)


class PairingDelegate(BasePairingDelegate):

    def __init__(self,
        address: Address,
        service: "SecurityService",
        **kwargs
    ):
        self.address = address
        self.service = service
        super().__init__(**kwargs)

    async def accept(self):
        return True

    async def confirm(self):
        logging.info(f"Pairing event: `just_works` (io_capability: {self.io_capability})")

        if not self.service.event_queue:
            return True

        event = PairingEvent(
            address=bytes(reversed(bytes(self.address))),
            just_works=Empty()
        )

        self.service.event_queue.put_nowait(event)
        answer = await anext(self.service.event_answer)
        assert answer.event == event

        return answer.confirm

    async def compare_numbers(self, number, digits=6):
        logging.info(f"Pairing event: `numeric_comparison` (io_capability: {self.io_capability})")

        if not self.service.event_queue:
            raise RuntimeError('security: unhandled number comparison request')

        event = PairingEvent(
            address=bytes(reversed(bytes(self.address))),
            numeric_comparison=number
        )

        self.service.event_queue.put_nowait(event)
        answer = await anext(self.service.event_answer)
        assert answer.event == event

        return answer.confirm

    async def get_number(self):
        logging.info(f"Pairing event: `passkey_entry_request` (io_capability: {self.io_capability})")

        if not self.service.event_queue:
            raise RuntimeError('security: unhandled number request')

        event = PairingEvent(
            address=bytes(reversed(bytes(self.address))),
            passkey_entry_request=Empty()
        )

        self.service.event_queue.put_nowait(event)
        answer = await anext(self.service.event_answer)
        assert answer.event == event

        return answer.passkey

    async def display_number(self, number, digits=6):
        logging.info(f"Pairing event: `passkey_entry_notification` (io_capability: {self.io_capability})")

        if not self.service.event_queue:
            raise RuntimeError('security: unhandled number display request')

        event = PairingEvent(
            address=bytes(reversed(bytes(self.address))),
            passkey_entry_notification=number
        )

        self.service.event_queue.put_nowait(event)


class SecurityService(SecurityServicer):

    def __init__(self, device: Device, io_capability):
        super().__init__()
        self.event_queue: asyncio.Queue = None
        self.event_answer: Optional[AsyncIterator[PairingEventAnswer]] = None
        self.device = device
        self.device.io_capability = io_capability
        self.device.pairing_config_factory = lambda connection: PairingConfig(
            delegate=PairingDelegate(
                connection.peer_address, self,
                io_capability=self.device.io_capability,
            )
        )

    async def OnPairing(self, event_answer, context):
        logging.info('OnPairing')

        self.event_queue = asyncio.Queue()
        self.event_answer = event_answer

        try:
            while event := await self.event_queue.get():
                yield event

        finally:
            self.event_queue = None
            self.event_answer = None

    # TODO: implement `WaitSecurity`

    async def Pair(self, request, context):
        connection_handle = int.from_bytes(request.connection.cookie.value, 'big')
        logging.info(f"Pair: {connection_handle}")

        connection: BumbleConnection = self.device.lookup_connection(connection_handle)
        assert connection

        asyncio.create_task(
            connection.pair() if connection.transport == BT_LE_TRANSPORT
            else connection.authenticate()
        )

        return Empty()

    # TODO: implement `DeleteBond`
