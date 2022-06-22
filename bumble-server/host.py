import logging

from bumble.core import BT_BR_EDR_TRANSPORT
from bumble.hci import Address

from pandora.host_pb2 import ReadLocalAddressResponse, ConnectResponse, \
    Connection
from pandora.host_grpc import HostServicer


class HostService(HostServicer):

    def __init__(self, device):
        self.device = device

    async def ReadLocalAddress(self, request, context):
        logging.info('ReadLocalAddress')
        return ReadLocalAddressResponse(
            address=bytes(reversed(bytes(self.device.public_address))))

    async def Connect(self, request, context):
        # Need to reverse bytes order since Bumble Address is using MSB.
        address = Address(bytes(reversed(request.address)))
        logging.info(f"Connect: {address}")

        try:
            logging.info("Connecting...")
            connection = await self.device.connect(
                address, transport=BT_BR_EDR_TRANSPORT)
            logging.info("Connected")

            logging.info("Authenticating...")
            await self.device.authenticate(connection)
            logging.info("Authenticated")

            logging.info("Enabling encryption...")
            await self.device.encrypt(connection)
            logging.info("Encryption on")

        except Exception as error:
            logging.error(error)

        logging.info(connection.handle)
        connection_handle = connection.handle.to_bytes(4, 'big')
        return ConnectResponse(connection=Connection(cookie=connection_handle))
