import argparse
import asyncio

from dut2ref.client import BumbleClient


async def main():
    parser = argparse.ArgumentParser(description="Trigger an ACL connection")
    parser.add_argument('-a', '--address',
                        type=str,
                        required=True,
                        help='Peer Bluetooth Classic address')
    args = parser.parse_args()

    ref = BumbleClient()
    await ref.open()
    local_address = await ref.read_local_address()
    print(local_address)
    await ref.connect(str(args.address))
    await ref.close()


if __name__ == '__main__':
    asyncio.run(main())
