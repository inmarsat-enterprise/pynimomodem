import logging
import os
import threading

import pytest

from pynimomodem import NimoModem, ModemLocation

SERIAL_PORT = os.getenv('SERIAL_PORT', '/dev/ttyUSB0')
log = logging.getLogger(__name__)


@pytest.fixture
def modem() -> NimoModem:
    return NimoModem(SERIAL_PORT)


mobile_id: str = ''
model: str = ''


def test_overlap_request(modem: NimoModem):
    def command_2():
        global mobile_id
        mobile_id = modem.get_mobile_id()
        log.info('Mobile ID: %s', mobile_id)
    def command_3():
        global model
        model = modem.get_model()
        log.info('Manufacturer: %s', model)
    concurrent_2 = threading.Timer(1, command_2)
    concurrent_3 = threading.Timer(2, command_3)
    concurrent_2.daemon = True
    concurrent_3.daemon = True
    concurrent_2.start()
    concurrent_3.start()
    loc = modem.get_location()
    log.info('Location: %s', loc)
    assert isinstance(loc, (ModemLocation, None))
    while not mobile_id or not model:
        pass
    assert mobile_id
    assert model
