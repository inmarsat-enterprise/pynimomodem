import logging
import os
import time

import pytest
from serial import Serial

from pynimomodem.nimomodem import (
    Location,
    Manufacturer,
    MessageState,
    NimoMessage,
    NimoModem,
    SatelliteAcquisitionDetail,
)
from pynimomodem.nimoconstants import (
    EventNotification,
)

SERIAL_PORT = os.getenv('SERIAL_PORT', '/dev/ttyUSB0')
log = logging.getLogger(__name__)


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
    assert modem._mfr().name == manufacturer


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
    assert isinstance(detail.beam_state, int)
    assert isinstance(detail.rssi, float)
    assert isinstance(detail.vcid, int) and detail.vcid in range(0, 4096)


def test_send_data_autoname(modem: NimoModem):
    test_data = 'Hello World!'.encode()
    message_name = modem.send_data(test_data)
    assert isinstance(message_name, str) and len(message_name) > 0


state_parsing_test_cases = [
    '"12345678",01.02,4,128,6,10,10',   # Orbcomm MO state
    '"FM01.01",01.01,0,128,2,20,20',    # Orbcomm MT state
    '"123456789101",4,128,6,10,10',     # Quectel MO state
    '"FM01.01",0,128,2,20,20',          # Quectel MT state
]
@pytest.mark.parametrize("test_input", state_parsing_test_cases)
def test__parse_message_states(modem: NimoModem, test_input: str):
    test_parameters = test_input.split(',')
    if len(test_parameters) == 6:
        modem._manufacturer = Manufacturer.QUECTEL
    else:
        modem._manufacturer = Manufacturer.ORBCOMM
        del test_parameters[1]
    is_mo = not test_input.startswith('"FM')   # not a great distinguisher but ok for test
    states = modem._parse_message_states(test_input, is_mo)
    assert isinstance(states, list) and len(states) == 1
    assert isinstance(states[0], NimoMessage)
    assert states[0].name == test_parameters[0].replace('"', '')
    if is_mo:
        assert states[0].state == MessageState.TX_COMPLETE
    else:
        assert states[0].state == MessageState.RX_COMPLETE
    assert states[0].length == int(test_parameters[4])
    assert states[0].bytes_delivered == int(test_parameters[5])


def test_get_mo_message_states(modem: NimoModem):
    message_states = modem.get_mo_message_states()
    assert isinstance(message_states, list)
    if len(message_states) > 0:
        for message_state in message_states:
            assert isinstance(message_state, NimoMessage)


def test_send_data_reject_invalid_sin(modem: NimoModem):
    test_data = b'\x00\x00\x01'
    with pytest.raises(ValueError) as exc_info:
        modem.send_data(test_data)
    assert 'SIN' in exc_info.value.args[0]


def test_send_data_reject_invalid_min(modem: NimoModem):
    test_data = 'Hello World'
    with pytest.raises(ValueError) as exc_info:
        modem.send_data(test_data.encode(), codec_min = 256)
    assert 'MIN' in exc_info.value.args[0]


def test_send_text(modem: NimoModem):
    message_name = modem.send_text('Hello World')
    assert isinstance(message_name, str) and message_name
    complete = False
    while not complete:
        statuses = modem.get_mo_message_states(message_name)
        if len(statuses) > 0:
            if statuses[0].state >= MessageState.TX_COMPLETE:
                complete = True


def test_large_message(modem: NimoModem):
    data = b'\x10'
    for b in range(1, 5000):
        data += b'\xff'
    message_name = modem.send_data(data)
    complete = False
    while not complete:
        statuses = modem.get_mo_message_states(message_name)
        if len(statuses) > 0:
            if statuses[0].state >= MessageState.TX_COMPLETE:
                complete = True


def test_cancel_message(modem: NimoModem):
    data = b'\x10'
    for b in range(1, 1000):
        data += b'\xff'
    message_name = modem.send_data(data)
    cancelled = modem.cancel_mo_message(message_name)
    assert cancelled


def test_get_mt_states(modem: NimoModem):
    mt_states = modem.get_mt_message_states()
    assert isinstance(mt_states, list)
    for mt_state in mt_states:
        assert isinstance(mt_state, NimoMessage)


def test_get_mt_message(modem: NimoModem):
    mt_states = modem.get_mt_message_states()
    assert len(mt_states) > 0
    message_name = mt_states[0].name
    mt_message = modem.get_mt_message(message_name)
    assert isinstance(mt_message, NimoMessage)
    assert mt_message.length > 0
    assert mt_message.bytes_delivered == mt_message.length
    assert len(mt_message.payload) == mt_message.length
    log.info('Message RawPayload: %s', [int(b) for b in mt_message.payload])


def test_receive_data(modem: NimoModem):
    mt_states = modem.get_mt_message_states()
    assert len(mt_states) > 0
    message_name = mt_states[0].name
    data = modem.receive_data(message_name)
    assert isinstance(data, bytes)
    log.info('Message RawPayload: %s', [int(b) for b in data])


def test_delete_mt_message(modem: NimoModem):
    mt_states = modem.get_mt_message_states()
    assert len(mt_states) > 0
    message_name = mt_states[0].name
    deleted = modem.delete_mt_message(message_name)
    assert deleted
    mt_states = modem.get_mt_message_states()
    assert len(mt_states) == 0


def test_get_set_gnss_mode(modem: NimoModem):
    test_initialize(modem)
    gnss_mode = modem.get_gnss_mode()
    assert isinstance(gnss_mode, int)
    gnss_mode_new = 1 if gnss_mode == 0 else 0
    success = modem.set_gnss_mode(gnss_mode_new)
    gnss_mode = modem.get_gnss_mode()
    assert success and gnss_mode == gnss_mode_new
    test_initialize(modem)


def test_get_set_gnss_refresh(modem: NimoModem):
    test_initialize(modem)
    gnss_refresh = modem.get_gnss_refresh()
    assert isinstance(gnss_refresh, int)
    gnss_refresh_new = 1 if gnss_refresh == 0 else 0
    success = modem.set_gnss_refresh(gnss_refresh_new)
    gnss_refresh = modem.get_gnss_refresh()
    assert success and gnss_refresh == gnss_refresh_new
    test_initialize(modem)


def test_get_nmea_data(modem: NimoModem):
    nmea_data = modem.get_nmea_data(gsv=True)
    assert isinstance(nmea_data, str)
    assert all(t in nmea_data for t in ['RMC', 'GGA', 'GSA', 'GSV'])
    assert len(nmea_data.split('\n')) >= 4


def test_get_location(modem: NimoModem):
    location = modem.get_location()
    if location is not None:
        assert isinstance(location, Location)
        assert location.latitude != 90.0
        assert location.longitude != 180.0


def test_get_set_event_mask(modem: NimoModem):
    test_initialize(modem)
    event_mask = modem.get_event_mask()
    assert isinstance(event_mask, int)
    new_mask = (EventNotification.MESSAGE_MT_RECEIVED |
                EventNotification.MESSAGE_MO_COMPLETE |
                EventNotification.EVENT_TRACE_CACHED)
    success = modem.set_event_mask(new_mask)
    assert success and modem.get_event_mask() == new_mask
    test_initialize(modem)


def bits_in_bitmask(n: int):
    while n:
        b = n & (~n+1)
        yield b
        n ^= b


def test_get_events_asserted(modem: NimoModem):
    test_initialize(modem)
    event_mask = EventNotification.GNSS_FIX_NEW
    modem.set_event_mask(event_mask)
    modem.set_gnss_refresh(1)
    time.sleep(1)
    asserted = modem.get_events_asserted_mask()
    assert asserted & EventNotification.GNSS_FIX_NEW
    for bit in bits_in_bitmask(asserted):
        log.info('Asserted: %s', EventNotification(bit).name)
    test_initialize(modem)


def test_get_set_qurc_ctl(modem: NimoModem):
    test_initialize(modem)
    if modem._mfr != Manufacturer.QUECTEL:
        with pytest.raises(ValueError):
            modem.get_qurc_ctl()
    else:
        qurc_ctl = modem.get_qurc_ctl()
        assert isinstance(qurc_ctl, int)


def test_get_power_mode(modem: NimoModem):
    """"""


def test_set_power_mode(modem: NimoModem):
    """"""


def test_get_wakeup_period(modem: NimoModem):
    """"""


def test_set_wakeup_period(modem: NimoModem):
    """"""


def test_powerdown(modem: NimoModem):
    """"""


def test_get_qwakeupway(modem: NimoModem):
    """"""


def test_get_qworkmode(modem: NimoModem):
    """"""


def test_set_qworkmode(modem: NimoModem):
    """"""


def test_get_deepsleep_enable(modem: NimoModem):
    """"""


def test_set_deepsleep_enable(modem: NimoModem):
    """"""
