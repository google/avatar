# Avatar with Android

Since Android provides an implementation of the [Pandora APIs](
https://github.com/google/bt-test-interfaces), Avatar can run with Android
devices.

## Setup

The standard Avatar setup on Android is to test a [Cuttlefish](
https://source.android.com/docs/setup/create/cuttlefish) virtual Android DUT
against a [Bumble](https://github.com/google/bumble) virtual Reference device
(REF).

Pandora APIs are implemented both on Android in a
[PandoraServer][pandora-server-code] app and on [Bumble](
https://github.com/google/bumble/tree/main/bumble/pandora). The communication
between the virtual Android DUT and the virtual Bumble Reference device is made
through [Rootcanal][rootcanal-code], a virtual Bluetooth Controller.

![Avatar Android architecture](
images/avatar-android-bumble-virtual-architecture-simplified.svg)

## Usage

There are two different command line interfaces to use Avatar on Android.

### Prerequisites

You must have a running CF instance. If not, you can run the following commands
from the root of your Android repository:

```shell
source build/envsetup.sh
lunch aosp_cf_x86_64_phone-userdebug
acloud create --local-image --local-instance
```

Note: For Googlers, from an internal Android repository, use the
`cf_x86_64_phone-userdebug` target instead. You can also use a CF remote
instance by removing `--local-instance`.

### `avatar` CLI (preferred)

You can run all the existing Avatar tests on Android by running the following
commands from the root of your Android repository:

```shell
cd packages/modules/Bluetooth
source android/pandora/test/envsetup.sh
avatar --help
avatar format # Format test files
avatar lint # Lint test files
avatar run --mobly-std-log  # '--mobly-std-log' to print mobly logs, silent otherwise
```

Note: If you have errors such as `ModuleNotFoundError: no module named pip`,
reset your Avatar cache by doing `rm -rf ~/.cache/avatar/venv`.

### `atest` CLI

You can also run all Avatar tests using [`atest`](
https://source.android.com/docs/core/tests/development/atest):

```shell
atest avatar -v # All tests in verbose
```

## Build a new Avatar test

Follow the instructions below to create your first Avatar test.

### Create a test class

Create a new Avatar test class file `codelab_test.py` in the Android Avatar
tests folder, `packages/modules/Bluetooth/android/pandora/test/`:

```python
from typing import Optional  # Avatar is strictly typed.

# Importing Mobly modules required for the test.
from mobly import base_test  # Mobly base test class .

# Importing Avatar classes and functions required for the test.
from avatar import PandoraDevices
from avatar.aio import asynchronous  # A decorator to run asynchronous functions.
from avatar.pandora_client import BumblePandoraClient, PandoraClient

# Importing Pandora gRPC message & enum types.
from pandora.host_pb2 import RANDOM, DataTypes


# The test class to test the LE (Bluetooth Low Energy) Connectivity.
class CodelabTest(base_test.BaseTestClass):
    devices: Optional[PandoraDevices] = None
    dut: PandoraClient
    ref: BumblePandoraClient  # `BumblePandoraClient` is a sub-class of `PandoraClient`

    # Method to set up the DUT and REF devices for the test (called once).
    def setup_class(self) -> None:
        self.devices = PandoraDevices(self)  # Create Pandora devices from the config.
        self.dut, ref = self.devices
        assert isinstance(ref, BumblePandoraClient)  # REF device is a Bumble device.
        self.ref = ref

    # Method to tear down the DUT and REF devices after the test (called once).
    def teardown_class(self) -> None:
        # Stopping all the devices if any.
        if self.devices: self.devices.stop_all()

    # Method to set up the test environment (called before each test).
    @asynchronous
    async def setup_test(self) -> None:
        # Reset DUT and REF devices asynchronously.
        await asyncio.gather(self.dut.reset(), self.ref.reset())

    # Method to write the actual test.
    def test_void(self) -> None:
        assert True  # This is a placeholder for the test body.
```

For now, your test class contains only a single `test_void`.

### Add a test class to Avatar test suite runner

Add the tests from your test class into
[Avatar Android test suite runner][avatar-android-suite-runner-code]:

```diff
diff --git a/android/pandora/test/main.py b/android/pandora/test/main.py
index a124306e8f..742e087521 100644
--- a/android/pandora/test/main.py
+++ b/android/pandora/test/main.py
@@ -1,11 +1,12 @@
 from mobly import suite_runner

+import codelab_test
 import example

 import logging
 import sys

-_TEST_CLASSES_LIST = [example.ExampleTest]
+_TEST_CLASSES_LIST = [example.ExampleTest, codelab_test.CodelabTest]
```

You can now try to run your test class using `avatar`:

```shell
avatar run --mobly-std-log --include-filter 'CodelabTest'  # All the CodelabTest tests
avatar run --mobly-std-log --include-filter 'CodelabTest#test_void' # Run only test_void
```

Or using `atest`:

```shell
atest avatar -v  # all tests
atest avatar:'CodelabTest#test_void' -v # Run only test_void
```

### Add a real test

You can add a new test to your test class by creating a new method `test_<>`,
which is implemented by a series of calls to the Pandora APIs of either the
Android DUT or the Bumble REF device and assert statement.

A call to a Pandora API is made using `<device>.<api>.<method>(<arguments>)`.
Pandora APIs and their descriptions are in
[`external/pandora/bt-test-interfaces`][pandora-api-code] or
[`package/module/Bluetooth/pandora/interfaces/pandora_experimental`][pandora-experimental-api-code].

For example, add the following test to your `codelab_test.py` test class:

```python
# Test the LE connection between the central device (DUT) and peripheral device (REF).
def test_le_connect_central(self) -> None:
    # Start advertising on the REF device, this makes it discoverable by the DUT.
    # The REF advertises as `connectable` and the own address type is set to `random`.
    advertisement = self.ref.host.Advertise(
        # Legacy since extended advertising is not yet supported in Bumble.
        legacy=True,
        connectable=True,
        own_address_type=RANDOM,
        # DUT device matches the REF device using the specific manufacturer data.
        data=DataTypes(manufacturer_specific_data=b'pause cafe'),
    )

    # Start scanning on the DUT device.
    scan = self.dut.host.Scan(own_address_type=RANDOM)
    # Find the REF device using the specific manufacturer data.
    peer = next((peer for peer in scan
        if b'pause cafe' in peer.data.manufacturer_specific_data))
    scan.cancel()  # Stop the scan process on the DUT device.

    # Connect the DUT device to the REF device as central device.
    connect_res = self.dut.host.ConnectLE(
        own_address_type=RANDOM,
        random=peer.random,  # Random REF address found during scanning.
    )
    advertisement.cancel()

    # Assert that the connection was successful.
    assert connect_res.connection
    dut_ref = connect_res.connection

    # Disconnect the DUT device from the REF device.
    self.dut.host.Disconnect(connection=dut_ref)
```

Then, run your new `test_le_connect_central` test:

```shell
avatar run --mobly-std-log --include-filter 'CodelabTest'
```

### Implement your own tests

Before starting, you should make sure you have clearly identified the tests you
want to build: see [Where should I start to implement Avatar tests?](
overview#designing-avatar-tests)

When your test is defined, you can implement it using the available
[stable Pandora APIs][pandora-api-code].

Note: You can find many test examples in
[`packages/modules/Bluetooth/android/pandora/test/`][avatar-android-tests-code].

**If you need an API which is not part of the finalized Pandora APIs to build
your test**:

1. If the API you need is **on the Android side**: you can also directly use the
   [experimental Pandora API][pandora-experimental-api-code], in the same
   fashion as the stable ones.

   Warning: those APIs are subject to changes.

1. If the API you need is on the Bumble side: you can also use the experimental
   Pandora APIs by creating custom [Bumble extensions](
   android-bumble-extensions).

1. If the API you need is not part of the experimental Pandora APIs:

  * Create an issue. The Avatar team will decide whether to create a new API or
    not. We notably don't want to create APIs for device specific behaviors.

  * If it is decided not to add a new API, you can instead access the Bumble
    Bluetooth stack directly within your test. For example:

    ```python
    @asynchronous
    async def test_pause_cafe(self) -> None:
        from bumble.core import BT_LE_TRANSPORT

        # `self.ref.device` an instance of `bumble.device.Device`
        connection = await self.ref.device.find_peer_by_name(  # type: ignore
            "Pause cafe",
            transport=BT_LE_TRANSPORT,
        )

        assert connection
        await self.ref.device.encrypt(connection, enable=True)  # type: ignore
    ```

## Contribution guide

### Modify the Avatar repository

All contributions to Avatar (not tests) must be submitted first to GitHub since
it is the source of truth for Avatar. To simplify the development process,
Android developers can make their changes on Android and get reviews on Gerrit
as usual, but then push it first to GitHub:

1. Create your CL in [`external/pandora/Avatar`][avatar-code].
1. Ask for review on Gerrit as usual.
1. Upon review and approval, the Avatar team creates a Pull Request on GitHub
   with you as the author. The PR is directly approved.
1. After it passes GitHub Avatar CI, the PR is merged.
1. Then, the Avatar team merges the change from GitHub to Android.

### Upstream experimental Pandora APIs

The Pandora team continuously works to stabilize new Pandora APIs. When an
experimental Pandora API is considered stable, it is moved from
[`package/module/Bluetooth/pandora/interfaces/pandora_experimental`][pandora-experimental-api-code]
to the official stable Pandora API repository in
[`external/pandora/bt-test-interfaces`][pandora-api-code].

### Upstream Android tests to the Avatar repository

On a regular basis, the Avatar team evaluates Avatar tests which have been
submitted to Android and upstream them to the Avatar repository in the
[`cases`](/cases/) folder if they are generic, meaning not related to Android
specifically.

Such added generic tests are removed from
[`packages/modules/Bluetooth/android/pandora/test/`][avatar-android-tests-code].

## Presubmit tests

All Avatar tests submitted in the
[Android Avatar tests folder][avatar-android-tests-code] and added to
[Avatar suite runner][avatar-android-suite-runner-code] as well as the tests in
the [generic Avatar tests folder][avatar-tests-code], are run in Android
Bluetooth presubmit tests (for every CL).

Note: Avatar tests will soon also be run regularly on physical devices in
Android postsubmit tests.

[pandora-server-code]: https://cs.android.com/android/platform/superproject/main/+/main:packages/modules/Bluetooth/android/pandora/server/

[rootcanal-code]: https://cs.android.com/android/platform/superproject/main/+/main:packages/modules/Bluetooth/tools/rootcanal

[pandora-api-code]: https://cs.android.com/android/platform/superproject/+/main:external/pandora/bt-test-interfaces/pandora

[pandora-experimental-api-code]: https://cs.android.com/android/platform/superproject/main/+/main:packages/modules/Bluetooth/pandora/interfaces/pandora_experimental/

[avatar-tests-code]: https://cs.android.com/android/platform/superproject/+/main:external/pandora/avatar/cases

[avatar-android-tests-code]: https://cs.android.com/android/platform/superproject/main/+/main:packages/modules/Bluetooth/android/pandora/test/

[avatar-code]: https://cs.android.com/android/platform/superproject/+/main:external/pandora/avatar

[avatar-android-suite-runner-code]: https://cs.android.com/android/platform/superproject/main/+/main:packages/modules/Bluetooth/android/pandora/test/main.py
