import logging

from dut2ref.clients import BumbleClient

MOBLY_CONTROLLER_CONFIG_NAME = 'BumbleDevice'


def create(configs):
    # For now, we only support one Bumble device at a time.
    bumble_device = BumbleDevice()
    bumble_device.open()
    return [bumble_device]


def destroy(bumble_devices):
    for bd in bumble_devices:
        bd.close()


def get_info(bumble_devices):
    return [bd.info for bd in bumble_devices]


class BumbleDevice(BumbleClient):

    def __init__(self):
        super().__init__()
        self.log = BumbleDeviceLoggerAdapter(logging.getLogger(), None)

    @property
    def info(self):
        return {'port': self.port}


class BumbleDeviceLoggerAdapter(logging.LoggerAdapter):

    def process(self, msg, kwargs):
        msg = f'[{MOBLY_CONTROLLER_CONFIG_NAME}] {msg}'
        return (msg, kwargs)
