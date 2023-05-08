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

"""Pandora device Mobly controller."""

import importlib

from avatar.pandora_client import PandoraClient
from typing import Any, Dict, List, Optional, cast

MOBLY_CONTROLLER_CONFIG_NAME = 'PandoraDevice'


def create(configs: List[Dict[str, Any]]) -> List[PandoraClient]:
    """Create a list of `PandoraClient` from configs."""

    def create_device(config: Dict[str, Any]) -> PandoraClient:
        module_name = config.pop('module', PandoraClient.__module__)
        class_name = config.pop('class', PandoraClient.__name__)

        module = importlib.import_module(module_name)
        return cast(PandoraClient, getattr(module, class_name)(**config))

    return list(map(create_device, configs))


def destroy(devices: List['PandoraClient']) -> None:
    """Destroy each `PandoraClient`"""
    for device in devices:
        device.close()


def get_info(devices: List['PandoraClient']) -> List[Optional[Dict[str, Any]]]:
    """Return the device info for each `PandoraClient`."""
    return [{'grpc_target': device.grpc_target, 'bd_addr': str(device.address)} for device in devices]
