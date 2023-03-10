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

from avatar.bumble_server.utils import BumbleServerLoggerAdapter
from bumble.device import Device
from bumble.profiles.asha_service import AshaService
from google.protobuf.empty_pb2 import Empty  # pytype: disable=pyi-error
from pandora.asha_grpc_aio import ASHAServicer
from pandora.asha_pb2 import CaptureAudioRequest, CaptureAudioResponse, RegisterRequest
from typing import AsyncGenerator, Optional


class ASHAService(ASHAServicer):
    device: Device
    asha_service: Optional[AshaService]

    def __init__(self, device: Device) -> None:
        self.log = BumbleServerLoggerAdapter(logging.getLogger(), {'service_name': 'Asha', 'device': device})
        self.device = device
        self.asha_service = None

    async def Register(self, request: RegisterRequest, context: grpc.ServicerContext) -> Empty:
        self.log.info('Register')
        # asha service from bumble profile
        self.asha_service = AshaService(request.capability, request.hisyncid, self.device)
        self.device.add_service(self.asha_service)  # type: ignore[no-untyped-call]
        return Empty()

    async def CaptureAudio(
        self, request: CaptureAudioRequest, context: grpc.ServicerContext
    ) -> AsyncGenerator[CaptureAudioResponse, None]:
        self.log.info('CaptureAudioData')

        if not self.asha_service:
            raise RuntimeError('The ASHA service has not been registered.')

        queue: asyncio.Queue[CaptureAudioResponse] = asyncio.Queue()
        handler = self.asha_service.on('data', queue.put_nowait)

        try:
            while data := await queue.get():
                yield CaptureAudioResponse(data=data)
        finally:
            self.asha_service.remove_listener('data', handler)
