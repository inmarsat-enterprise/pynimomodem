import logging
import os
import time

import pytest
from serial import Serial

from pynimomodem.atcommandbuffer import AtCommandBuffer
from pynimomodem.constants import AtErrorCode

SERIAL_PORT = os.getenv('SERIAL_PORT', '/dev/ttyUSB0')
log = logging.getLogger(__name__)


@pytest.fixture(autouse=True)
def command_buffer():
    serial = Serial(SERIAL_PORT)
    if not serial.is_open:
        raise OSError('Unable to connect to modem')
    atbuffer = AtCommandBuffer(serial)
    yield atbuffer
    # reset defaults after use
    atbuffer.send_at_command('AT&F;&W')
    atbuffer.read_at_response()


@pytest.mark.parametrize('timeout', [None, 5])
def test_at_timeout(command_buffer: AtCommandBuffer, timeout: int):
    """Requires that a modem is NOT connected on serial."""
    command_buffer.send_at_command('ATZ')
    read_start_time = time.time()
    result = command_buffer.read_at_response(timeout=timeout)
    read_stop_time = time.time()
    assert result == AtErrorCode.TIMEOUT
    expected = timeout or 3
    assert int(read_stop_time - read_start_time) == expected
    response = command_buffer.get_response()
    assert response == ''


def test_command_response_verbose_ok(command_buffer: AtCommandBuffer):
    """Requires that a modem is connected on serial."""
    command_buffer.send_at_command('ATZ')
    result = command_buffer.read_at_response()
    assert result == AtErrorCode.OK
    response: str = command_buffer.get_response()
    assert response == ''


def test_command_response_short_ok(command_buffer: AtCommandBuffer):
    """"""
    command_buffer.send_at_command('ATV0')
    result = command_buffer.read_at_response()
    assert result == AtErrorCode.OK
    response = command_buffer.get_response()
    assert response == ''


def test_prefix_removal(command_buffer: AtCommandBuffer):
    """"""
    command_buffer.send_at_command('AT Z;+GSN')
    prefix = '+GSN:'
    result = command_buffer.read_at_response(prefix, timeout=900)
    if result == AtErrorCode.CRC_CONFIG_MISMATCH:
        command_buffer.send_at_command('AT+GSN')
        result = command_buffer.read_at_response(prefix)
    assert result == AtErrorCode.OK
    response = command_buffer.get_response()
    assert response and prefix not in response


def test_crc(command_buffer: AtCommandBuffer):
    """"""
    command_buffer.send_at_command('AT Z;%CRC=1')
    result = command_buffer.read_at_response()
    assert result == AtErrorCode.OK
    assert command_buffer.crc is True
    command_buffer.send_at_command('AT')
    result = command_buffer.read_at_response()
    assert result == AtErrorCode.OK


def test_short_error(command_buffer: AtCommandBuffer):
    """"""
    command_buffer.send_at_command('ATV0')
    command_buffer.read_at_response()
    command_buffer.send_at_command('AT+FAKE')
    result = command_buffer.read_at_response()
    assert result == AtErrorCode.ERROR
    assert command_buffer.get_response() == ''


def test_short_error_crc(command_buffer: AtCommandBuffer):
    """"""
    command_buffer.send_at_command('AT V0;%CRC=1')
    command_buffer.read_at_response()
    command_buffer.send_at_command('AT+FAKE')
    result = command_buffer.read_at_response()
    assert result == AtErrorCode.ERROR
    assert command_buffer.get_response() == ''
