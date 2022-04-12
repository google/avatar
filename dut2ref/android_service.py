import time

from mobly.controllers.android_device_lib.services.base_service \
    import BaseService

from dut2ref.clients import AndroidClient

ANDROID_SERVER_PACKAGE = 'com.android.blueberry'


class AndroidService(AndroidClient, BaseService):

    def __init__(self, device, configs=None):
        AndroidClient.__init__(self)
        BaseService.__init__(self, device, configs=None)
        self._is_alive = False

    @property
    def is_alive(self):
        return self._is_alive

    def start(self):
        # Start Blueberry Android gRPC server.
        self._device.adb._exec_adb_cmd(
            'shell',
            f'am instrument -r -e Debug false {ANDROID_SERVER_PACKAGE}/.Main',
            shell=False,
            timeout=None,
            stderr=None)

        self._device.adb.forward([f'tcp:{self.port}', f'tcp:{self.port}'])

        # Wait a few seconds for the Android gRPC server to be started.
        time.sleep(3)

        self.open()

        self._is_alive = True

    def stop(self):
        self.close()

        # Stop Blueberry Android gRPC server.
        self._device.adb._exec_adb_cmd(
            'shell',
            f'am force-stop {ANDROID_SERVER_PACKAGE}',
            shell=False,
            timeout=None,
            stderr=None)

        self._device.adb.forward(['--remove', f'tcp:{self.port}'])

        self._is_alive = False
