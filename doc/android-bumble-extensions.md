# Android Bumble extensions

While [experimental Pandora API][pandora-experimental-api-code] are implemented
for Android, they may not be for Bumble. When writing Android Avatar tests, if
you need one of these APIs on Bumble, you can implement it by adding a custom
service.

Note: Before going further, make sure you read the
[Implementing your own tests](android-guide#implementing-your-own-tests)
section of the Avatar Android guide.

In the following example, we will add stub files required to write HID tests for
the [`hid.proto`][hid-proto] interface.

Note: The code for this example is available in a [WIP CL][hid-example].

## Create a new test class

Follow [Create a test class](android-guide#create-a-test-class) to create a
`HidTest` test class in `hid_test.py`.

## Create a Bumble HID extension

Create an HID extension file:

```shell
cd packages/modules/Bluetooth/
touch pandora/server/bumble_experimental/hid.py
```

Add the following code to it:

```python
import grpc
import logging

from bumble.device import Device
from pandora_experimental.hid_grpc import (
    SendHostReportRequest,
    SendHostReportResponse,
)
from pandora_experimental.hid_grpc_aio import HIDServicer

# This class implements the HID experimental Pandora interface.
class HIDService(HIDServicer):
    device: Device

    def __init__(self, device: Device) -> None:
        self.device = device

    async def SendHostReport(
        self,
        request: SendHostReportRequest,
        context: grpc.ServicerContext
    ) -> SendHostReportResponse:
        logging.info(
            f'SendHostReport(address={request.address}, '
            f'type={request.report_type}, report="{request.report}")'
        )
        # You should implement SendHostReport here by doing direct call to the
        # Bumble instance (i.e. `self.device`).
        return SendHostReportResponse()
```

## Add an HID test to your test class

In `hid_test.py`:

```python
def test_report(self) -> None:
    from pandora_experimental.hid_grpc import HID, HidReportType
    HID(self.ref.channel).SendHostReport(
        address=self.dut.address,
        report_type=HidReportType.HID_REPORT_TYPE_INPUT,
        report="pause cafe"
    )
```

### Add your HID test class to Avatar test suite runner

```diff
diff --git a/android/pandora/test/main.py b/android/pandora/test/main.py
--- a/android/pandora/test/main.py
+++ b/android/pandora/test/main.py
@@ -3,18 +3,22 @@ from avatar import bumble_server

 import example
 import gatt_test
+import hid_test

 import logging
 import sys

 from bumble_experimental.gatt import GATTService
 from pandora_experimental.gatt_grpc_aio import add_GATTServicer_to_server
+from bumble_experimental.hid import HIDService
+from pandora_experimental.hid_grpc_aio import add_HIDServicer_to_server

-_TEST_CLASSES_LIST = [example.ExampleTest, gatt_test.GattTest]
+_TEST_CLASSES_LIST = [example.ExampleTest, gatt_test.GattTest, hid_test.HidTest]


 def _bumble_servicer_hook(server: bumble_server.Server) -> None:
   add_GATTServicer_to_server(GATTService(server.bumble.device), server.server)
+  add_HIDServicer_to_server(HIDService(server.bumble.device), server.server)


 if __name__ == "__main__":
```

You can now run your new HID test:

```shell
avatar run --mobly-std-log --include-filter 'HidTest'
```

[pandora-experimental-api-code]: https://cs.android.com/android/platform/superproject/+/main:packages/modules/Bluetooth/pandora/interfaces/pandora_experimental/

[hid-proto]: https://cs.android.com/android/platform/superproject/main/+/main:packages/modules/Bluetooth/pandora/interfaces/pandora_experimental/hid.proto

[hid-example]: https://android-review.git.corp.google.com/c/platform/packages/modules/Bluetooth/+/2454811
