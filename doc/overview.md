# Avatar

Avatar is a python Bluetooth testing tool orchestrating multiple devices which
implement [Pandora APIs](https://github.com/google/bt-test-interfaces) to
automate Bluetooth interoperability and functional tests.

## Main architecture

Avatar is built around 4 key components:

* [Pandora APIs](https://github.com/google/bt-test-interfaces): They provide a
  common abstraction for Avatar to interact with all Bluetooth implementations,
  exposing all standard Bluetooth capabilities over [gRPC](https://grpc.io/).
* [Bumble](https://github.com/google/bumble): a python Bluetooth stack which
  can be used as a reference against any DUT.
* [Rootcanal][rootcanal-code]: A virtual Bluetooth Controller which emulates the
  Bluetooth communication between the devices being tested. It is notably
  integrated in Cuttlefish (CF), an Android virtual device.
* [Mobly](https://github.com/google/mobly): Avatar core python test runner.

For example, here is Avatar Android architecture:

![Avatar Android architecture](
images/avatar-android-bumble-virtual-architecture-simplified.svg)

A basic Avatar test is built by calling a Pandora API exposed by the DUT to
trigger a Bluetooth action and calling another Pandora API on a Reference
device (REF) to verify that this action has been correctly executed.

For example:

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

Avatar tests requires DUT and REF to provide a Pandora gRPC server which
implements the Pandora APIs and exposes them.

## Bumble as a reference device

By default, Avatar uses Bumble as a reference device. **Bumble is very practical
at emulating non-Android interoperability behaviors**: because it is written in
python and thus interpreted, its behavior can be overridden directly within the
tests by using direct python calls to Bumble internal functions when no Pandora
API is available (see [Implementing your own tests](
android-guide#implementing-your-own-tests)).

For example, using another Android device to emulate an interoperability
behavior of a specific headset would require building dedicated hooks in the
Android Bluetooth stack and the corresponding APIs which wouldn't be practical.

However, other setups are also supported (see [Extended architecture](
#extended-architecture)).

## Types of Avatar tests

Avatar principally addresses 2 types of tests:

### Functional tests

* Verify that the DUT is meeting a required specification.
* This can be either the official Bluetooth specification or a vendor
  specification (for example, Google's ASHA specification).
* Aim to address all functional tests not supported by the official Bluetooth
  Profile Tuning Suite (PTS).

### Interoperability regression tests

* Built by isolating and simulating only the problematic behavior of a peer
  device in Bumble after it has been discovered.
* Effectively scalable because it would be impossible to set up a dedicated
  physical test bench for each peer device presenting an interoperability issue.

### Examples

* [Android ASHA central tests][asha-central-tests-code]
* [Android GATT read characteristic while pairing test][gatt-test-example-code]

## Design Avatar tests

There are different approaches to identify new Avatar tests to implement:

### From the Bluetooth specification (or a Google specification)

The first approach is for creating functional tests: mandatory behaviors are
identified in the Bluetooth specification and corresponding test cases are
defined, and then implemented, except for test cases which are already covered
by PTS and which must be implemented with PTS-bot. This helps cover most of the
usual flows in the Bluetooth stack, and prevent any new changes to break them.

For example: [ASHA central tests][asha-central-tests-spec] (identified from the
ASHA specification).

This approach applies to all layers of the stack and should in general be
prioritized over the other approaches because breaking any of those usual flows
likely translates into a top priority issue (since a large number of devices
can be impacted).

### From a bug fix

The second approach is for creating interoperability regression tests: in most
cases, interoperability issues are discovered in Dog Food or production, due to
the extremely large number of Bluetooth devices on the market, which cannot be
tested preventively, even manually.

When such a bug is fixed, Avatar can be leveraged to build a corresponding
regression test.

### From a coverage report

The third approach is to start from a code coverage report: uncovered code
paths are identified and corresponding Avatar tests are implemented to target
them.

## Extended architecture

Avatar is capable to handle any setup with multiple devices which implement
the Pandora APIs. Avatar tests can be run physically or virtually (with
Rootcanal).

![Avatar Android architecture](
images/avatar-extended-architecture-simplified.svg)

Avatar notably supports the following setups:

* Bumble DUT vs Bumble REF
* Android DUT vs Bumble REF
* Android DUT vs Android REF

[rootcanal-code]: https://cs.android.com/android/platform/superproject/+/main:packages/modules/Bluetooth/tools/rootcanal/

[asha-central-tests-code]: https://cs.android.com/android/platform/superproject/+/main:packages/modules/Bluetooth/android/pandora/test/asha_test.py

[gatt-test-example-code]: https://r.android.com/2470981

[asha-central-tests-spec]: https://docs.google.com/document/d/1HmihYrjBGDys4FAEgh05e5BHPMxNUiz8QIOYez9GT1M/edit?usp=sharing
