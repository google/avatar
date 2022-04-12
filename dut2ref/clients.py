import grpc

from blueberry.host_grpc import Host
from dut2ref.utils import Address

BUMBLE_SERVER_PORT = 7999
ANDROID_SERVER_PORT = 8999


class BaseClient:

    def __init__(self, port):
        self.port = port

    def open(self):
        self.channel = grpc.insecure_channel(f'localhost:{self.port}')
        self.host = Host(self.channel)

    def close(self):
        self.channel.close()

    def read_local_address(self):
        read_local_address_response = self.host.ReadLocalAddress()
        return Address(read_local_address_response.address)


class BumbleClient(BaseClient):

    def __init__(self):
        super().__init__(BUMBLE_SERVER_PORT)


class AndroidClient(BaseClient):

    def __init__(self):
        super().__init__(ANDROID_SERVER_PORT)
