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

import logging

from bumble.device import Device
from bumble.profiles.asha_service import AshaService

from pandora.asha_grpc import ASHAServicer

from google.protobuf.empty_pb2 import Empty


class ASHAService(ASHAServicer):
    def __init__(self, device: Device):
        self.device = device

        super().__init__()

    async def Register(self, request, context):
        logging.info('Register')
        # asha service from bumble profile
        self.asha_service = AshaService(request.capability, request.hisyncid, self.device)
        self.device.add_service(self.asha_service)
        return Empty()
