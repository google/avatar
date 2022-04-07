import grpc.aio

from blueberry.host_grpc import Host

BUMBLE_SERVER_PORT = 7999


class BumbleClient:

    async def open(self):
        self.channel = grpc.aio.insecure_channel(
            f'localhost:{BUMBLE_SERVER_PORT}')
        await self.channel.channel_ready()

        self.host = Host(self.channel)

    async def read_local_address(self):
        read_local_address_response = await self.host.ReadLocalAddress()
        return read_local_address_response.address

    async def connect(self, address):
        await self.host.Connect(address=address.encode('utf-8'))

    async def close(self):
        await self.channel.close()
