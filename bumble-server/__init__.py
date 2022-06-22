"""Pandora Bumble Server."""

__version__ = "0.0.1"

import asyncio
import logging
import os

import grpc
from bumble.device import Device
from bumble.transport import open_transport

from bumble.a2dp import make_audio_sink_service_sdp_records

from pandora.host_grpc import add_HostServicer_to_server
from host import HostService

BUMBLE_SERVER_PORT = 7999
ROOTCANAL_PORT_CUTTLEFISH = 7300

current_dir = os.path.dirname(os.path.realpath(__file__))

async def serve():

    # Open Bumble HCI.
    async with await open_transport(
            f'tcp-client:127.0.0.1:{ROOTCANAL_PORT_CUTTLEFISH}') as hci:

        # Device definition, for now hardcoded.
        device = Device.from_config_file_with_hci(
                f'{current_dir}/device_config.json', hci.source, hci.sink)
        device.classic_enabled = True
        service_record_handle = 0x00010001
        device.sdp_service_records = {
            service_record_handle: make_audio_sink_service_sdp_records(
                service_record_handle)
        }

        # Power on device.
        await device.power_on()

        # Start gRPC server.
        server = grpc.aio.server()
        add_HostServicer_to_server(HostService(device), server)
        server.add_insecure_port(f'localhost:{BUMBLE_SERVER_PORT}')
        await server.start()
        await server.wait_for_termination()

        # Close Bumble HCI.
        await hci.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(serve())
