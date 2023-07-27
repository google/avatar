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

"""Bumble device Mobly controller."""

import asyncio
import avatar.aio

from bumble.pandora.device import PandoraDevice as BumblePandoraDevice
from typing import Any, Dict, List, Optional

MOBLY_CONTROLLER_CONFIG_NAME = 'BumbleDevice'


def create(configs: List[Dict[str, Any]]) -> List[BumblePandoraDevice]:
    """Create a list of `BumbleDevice` from configs."""
    return [BumblePandoraDevice(config) for config in configs]


def destroy(devices: List[BumblePandoraDevice]) -> None:
    """Destroy each `BumbleDevice`"""

    async def close_devices() -> None:
        await asyncio.gather(*(device.close() for device in devices))

    avatar.aio.run_until_complete(close_devices())


def get_info(devices: List[BumblePandoraDevice]) -> List[Optional[Dict[str, str]]]:
    """Return the device info for each `BumblePandoraDevice`."""
    return [device.info() for device in devices]
