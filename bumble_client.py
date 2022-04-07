import logging

from google.protobuf import empty_pb2
import grpc

import host_pb2
import host_pb2_grpc

BUMBLE_SERVER_PORT = 7999


def read_local_address(host_stub):
    return host_stub.ReadLocalAddress(empty_pb2.Empty())


def run():
    with grpc.insecure_channel(f'localhost:{BUMBLE_SERVER_PORT}') as channel:
        host_stub = host_pb2_grpc.HostStub(channel)
        local_address = read_local_address(host_stub).address.decode('utf-8')
        print(local_address)


logging.basicConfig()
run()
