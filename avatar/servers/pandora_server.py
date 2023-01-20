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


"""Interface for controller-specific Pandora server management."""

import types
from typing import Generic, TypeVar

from avatar.pandora_client import PandoraClient


# Generic type for `PandoraServer`.
TDevice = TypeVar('TDevice')

class PandoraServer(Generic[TDevice]):
    """Abstract interface to manage the Pandora gRPC server on the device."""

    MOBLY_CONTROLLER_MODULE: types.ModuleType

    device: TDevice

    def __init__(self, device: TDevice) -> None:
        """Creates a PandoraServer.

        Args:
            device: A Mobly controller instance.
        """
        self.device = device

    def start(self) -> PandoraClient:
        """Sets up and starts the Pandora server on the device."""
        assert isinstance(self.device, PandoraClient)
        return self.device

    def stop(self) -> None:
        """Stops and cleans up the Pandora server on the device."""
