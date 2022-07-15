class Address(bytes):

    def __new__(cls, address):
        if type(address) is bytes:
            address_bytes = address
        elif type(address) is str:
            address_bytes = bytes.fromhex(address.replace(':', ''))
        else:
            raise ValueError('Invalid address format')

        if len(address_bytes) != 6:
            raise ValueError('Invalid address length')

        return bytes.__new__(cls, address_bytes)

    def __str__(self):
        return ':'.join([f'{x:02X}' for x in self])
