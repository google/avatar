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
import grpc
import logging

from . import utils
from bumble.device import Device, Connection as BumbleConnection
from bumble.profiles.asha_service import AshaService as BumbleAshaService
from google.protobuf.empty_pb2 import Empty  # pytype: disable=pyi-error
from pandora.asha_grpc_aio import AshaServicer
from pandora.asha_pb2 import RegisterRequest, CaptureAudioResponse
from typing import AsyncGenerator, Optional


class AshaService(AshaServicer):
    device: Device
    asha_service: Optional[BumbleAshaService]

    def __init__(self, device: Device) -> None:
        self.log = utils.BumbleServerLoggerAdapter(logging.getLogger(), {'service_name': 'Asha', 'device': device})
        self.device = device
        self.asha_service = None

    @utils.rpc
    async def Register(self, request: RegisterRequest, context: grpc.ServicerContext) -> Empty:
        self.log.info('Register')
        # asha service from bumble profile
        self.asha_service = BumbleAshaService(request.capability, request.hisyncid, self.device)
        self.device.add_service(self.asha_service)  # type: ignore[no-untyped-call]
        return Empty()

    @utils.rpc
    async def CaptureAudio(self, request, context) -> AsyncGenerator[CaptureAudioResponse, None]:
        connection_handle = int.from_bytes(request.connection.cookie.value, 'big')
        logging.info(f'CaptureAudioData connection_handle:{connection_handle}')

        if not (connection := self.device.lookup_connection(connection_handle)):
            raise RuntimeError(f"Unknown connection for connection_handle:{connection_handle}")

        queue: asyncio.Queue[bytes] = asyncio.Queue()

        def on_data(asha_connection: BumbleConnection, data: bytes):
            if asha_connection == connection:
                queue.put_nowait(data)

        self.asha_service.on('data', on_data)

        try:
            while data := await queue.get():
                yield CaptureAudioResponse(data=data)
        finally:
            self.asha_service.remove_listener('data', on_data)
            queue = asyncio.Queue()
