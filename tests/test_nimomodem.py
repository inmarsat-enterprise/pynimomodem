import os
import pytest

from serial import Serial

from pynimomodem.nimomodem import NimoModem, SatelliteAcquisitionDetail

SERIAL_PORT = os.getenv('SERIAL_PORT', '/dev/ttyUSB0')


@pytest.fixture
def modem() -> NimoModem:
    return NimoModem(Serial(SERIAL_PORT))


def test_is_connected(modem: NimoModem):
    assert modem.is_connected()


def test_await_boot(modem: NimoModem):
    assert modem.await_boot(600)


def test_get_last_error_code(modem: NimoModem):
    last_error_code = modem.get_last_error_code()
    assert isinstance(last_error_code, int)


def test_initialize(modem: NimoModem):
    assert modem.initialize()


def test_crc(modem: NimoModem):
    assert modem.set_crc(True)
    assert modem.crc_enabled
    assert modem.set_crc(False)
    assert not modem.crc_enabled


def test_reset_factory_config(modem: NimoModem):
    modem.set_crc(True)
    assert modem.crc_enabled
    assert modem.reset_factory_config()
    assert not modem.crc_enabled
    assert modem.save_config()


def test_save_config(modem: NimoModem):
    assert modem.set_crc(True)
    assert modem.crc_enabled
    assert modem.initialize()
    assert not modem.crc_enabled
    assert modem.set_crc(True)
    assert modem.crc_enabled
    assert modem.save_config()
    assert modem.initialize()
    assert modem.crc_enabled
    assert modem.set_crc(False)
    assert modem.save_config()
    assert modem.initialize()
    assert not modem.crc_enabled


def test_get_mobile_id(modem: NimoModem):
    mobile_id = modem.get_mobile_id()
    assert isinstance(mobile_id, str)
    assert len(mobile_id) == 15
    assert modem._mobile_id == mobile_id


def test_get_manufacturer(modem: NimoModem):
    manufacturer = modem.get_manufacturer()
    assert isinstance(manufacturer, str)
    assert manufacturer in ['ORBCOMM', 'QUECTEL']
    assert modem._manufacturer == manufacturer
    assert modem._mfr_id().name == manufacturer


def test_get_firmware_version(modem: NimoModem):
    fw_version = modem.get_firmware_version()
    assert isinstance(fw_version, str) and len(fw_version) > 0


def test_get_system_time(modem: NimoModem):
    systime = modem.get_system_time()
    assert isinstance(systime, int) and systime > 0


def test_transmit_allowed(modem: NimoModem):
    assert modem.is_transmit_allowed()


def test_is_blocked(modem: NimoModem):
    assert not modem.is_blocked()


def test_is_muted(modem: NimoModem):
    assert not modem.is_muted()


def test_is_updating_network(modem: NimoModem):
    assert not modem.is_updating_network()


def test_get_satellite_status(modem: NimoModem):
    assert isinstance(modem.get_satellite_status(), int)


def test_get_rssi(modem: NimoModem):
    rssi = modem.get_rssi()
    assert isinstance(rssi, float) and rssi > 0


def test_get_signal_quality(modem: NimoModem):
    signal_quality = modem.get_signal_quality()
    assert isinstance(signal_quality, int) and signal_quality > 0


def test_get_acquisition_detail(modem: NimoModem):
    detail = modem.get_acquisition_detail()
    assert isinstance(detail, SatelliteAcquisitionDetail)
    assert isinstance(detail.ctrl_state, int)
    assert isinstance(detail.beam_search_state, int)
    assert isinstance(detail.rssi, float)
    assert isinstance(detail.vcid, int) and detail.vcid in range(0, 4096)


def test_send_data():
    assert False


def test_send_text():
    assert False
