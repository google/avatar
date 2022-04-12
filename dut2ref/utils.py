class Address:

    def __init__(self, address):
        if type(address) is bytes:
            self.address_bytes = address
        elif type(address) is str:
            self.address_bytes = bytes.fromhex(address.replace(':', ''))
        else:
            raise ValueError('Invalid address format')

        if len(self.address_bytes) != 6:
            raise ValueError('Invalid address length')

    def __bytes__(self):
        return self.address_bytes

    def __str__(self):
        return ':'.join([f'{x:02X}' for x in self.address_bytes])
