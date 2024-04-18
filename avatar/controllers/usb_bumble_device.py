# Copyright 2024 Google LLC
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

"""UsbDevice Bumble Mobly controller."""


from bumble.pandora.device import PandoraDevice as BumblePandoraDevice
from typing import Any, Dict, List

MOBLY_CONTROLLER_CONFIG_NAME = 'UsbDevice'


def create(configs: List[Dict[str, Any]]) -> List[BumblePandoraDevice]:
    """Create a list of `BumbleDevice` from configs."""

    def transport_from_id(id: str) -> str:
        return f'pyusb:!{id.removeprefix("usb:")}'

    return [BumblePandoraDevice(config={'transport': transport_from_id(config['id'])}) for config in configs]


from .bumble_device import destroy
from .bumble_device import get_info

__all__ = ["MOBLY_CONTROLLER_CONFIG_NAME", "create", "destroy", "get_info"]
