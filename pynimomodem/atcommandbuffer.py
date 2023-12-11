"""AT command buffer parsing for a NIMO modem.

This module provides a bidirectional buffer model for sendind and receiving
AT commands on a serial link to a satellite modem following V.25 spec.

"""
import logging
import threading
import time

from serial import Serial

from .constants import AtErrorCode, AtParsingState
from .crcxmodem import apply_crc, validate_crc
from .nimoutils import dprint, vlog

VLOG_TAG = 'atcommand'
DEFAULT_AT_TIMEOUT = 3   # seconds
VRES_OK = '\r\nOK\r\n'
VRES_ERR = '\r\nERROR\r\n'
RES_OK = '0\r'
RES_ERR = '4\r'

_log = logging.getLogger(__name__)


class AtCommandBuffer:
    """A command/response buffer for communicating with a NIMO modem.
    
    Attributes:
        serial (serial.Serial): The Serial object/stream used for communications
        echo (bool): Echo enabled on commands (default True)
        verbose (bool): Verbose response codes (default True)
        quiet (bool): Suppressed response codes (default False)
        crc (bool): CRC/checksum request/response enabled (default False)
        ready (threading.Event): Blocks new requests until pending response
            has completed or timed out.
    
    """
    def __init__(self, serial: Serial) -> None:
        self.echo: bool = True
        self.verbose: bool = True
        self.quiet: bool = False
        self.crc: bool = False
        if not isinstance(serial, Serial):
            raise ValueError('Invalid serial port')
        if vlog(VLOG_TAG):
            _log.debug('Connecting to %s (%d baud)',
                       serial.name, serial.baudrate)
        self.serial = serial
        self._char_delay: float = 8 / serial.baudrate
        self._pending_command: str = None
        self._rx_buffer: str = ''
        self.ready = threading.Event()
        self.ready.set()
    
    def is_data_waiting(self) -> bool:
        """Indicates if data is in the serial receive buffer."""
        return self.serial.in_waiting > 0
    
    def read_rx_buffer(self, timeout: int = 0, read_until: str = '') -> 'str|None':
        """Reads data from the serial receive buffer.
        
        Args:
            timeout (int): Optional timeout in seconds to wait for data.
                If 0, will stop reading when no character is waiting.
        
        Returns:
            The data string if any was present, else `None`.
            
        """
        if not isinstance(timeout, int):
            timeout = 0
        self.serial.flush()   # wait for anything sent prior to be done
        rx_data = ''
        start_time = time.time()
        while (time.time() - start_time < timeout or timeout == 0):
            while (self.serial.in_waiting > 0):
                rx_data += self._read()
            if timeout == 0 or rx_data.endswith(read_until):
                break
        if vlog(VLOG_TAG):
            if rx_data:
                _log.debug('Read from serial: %s', dprint(rx_data))
            else:
                _log.debug('No data waiting on serial buffer')
        return rx_data
    
    def send_at_command(self, at_command: str) -> None:
        """Submits an AT command to the NIMO modem to solicit a response.
        
        Use `read_at_response` then `get_resopnse` after sending the command.
        
        Args:
            at_command: The command to send.
        
        """
        if vlog(VLOG_TAG) and not self.ready.is_set():
            _log.debug('Waiting for prior command completion')
        self.ready.wait()
        self.ready.clear()
        if 'ATS80?' in at_command:
            _log.debug('Somebody is querying error state!')
        dump_buffer = self.read_rx_buffer()
        if dump_buffer:
            _log.warning('Dumping RX buffer: %s', dprint(dump_buffer))
        self._pending_command = at_command
        if self.crc and '*' not in at_command:
            self._pending_command = apply_crc(at_command)
        self._pending_command += '\r'
        if vlog(VLOG_TAG):
            _log.debug('Sending on serial: %s', dprint(self._pending_command))
        self.serial.write(self._pending_command.encode())
        self.serial.flush()   # ensure it gets sent
    
    def read_at_response(self,
                         prefix: str = None,
                         timeout: int = DEFAULT_AT_TIMEOUT,
                         tick: int = 0) -> AtErrorCode:
        """Parses the pending AT command response into a buffer.
        
        Use `send_at_command` prior to calling.
        Use `get_response` to retrieve the parsed response.
        
        Args:
            prefix: Optional prefix to remove from the response.
            timeout: Maximum time in seconds to wait for response (default 3)
            tick: Optional debug for timeout countdown in seconds
        
        Returns:
            Error code indicating success or reason for parsing error.
        
        Raises:
            `OSError` if there is no pending command.
        
        """
        if not isinstance(timeout, int):
            timeout = DEFAULT_AT_TIMEOUT
        if not self._pending_command:
            raise OSError('No pending command to read response for')
        if vlog(VLOG_TAG):
            _log.debug('Parsing response for %s', dprint(self._pending_command))
        self._rx_buffer = ''
        parsing = AtParsingState.ECHO if self.echo else AtParsingState.RESPONSE
        result_ok: bool = False
        crc_found: bool = False
        error: AtErrorCode = AtErrorCode.OK
        peeked: str = ''
        start_time = time.time()
        countdown = timeout
        while (time.time() - start_time < timeout and
               parsing < AtParsingState.OK):
            while ((self.serial.in_waiting > 0 or peeked) and
                   parsing < AtParsingState.OK):
                if peeked:
                    self._rx_buffer += peeked
                    peeked = ''
                else:
                    self._rx_buffer += self._read()
                last = self._rx_buffer[-1]
                if last == '\n':
                    if self._rx_buffer.endswith(VRES_OK):
                        result_ok = True
                        parsing = self._parsing_ok()
                    elif self._rx_buffer.endswith(VRES_ERR):
                        parsing = self._parsing_error()
                    elif parsing == AtParsingState.CRC:
                        if vlog(VLOG_TAG):
                            _log.debug('CRC parsing complete')
                        if not result_ok:
                            parsing = AtParsingState.ERROR
                        else:
                            if validate_crc(self._rx_buffer):
                                parsing = AtParsingState.OK
                            else:
                                _log.error('Invalid CRC')
                                parsing = AtParsingState.ERROR
                                error = AtErrorCode.INVALID_CRC
                                result_ok = False
                    # else response line terminator - keep parsing
                elif last == '\r':
                    if self._rx_buffer == self._pending_command:
                        if vlog(VLOG_TAG):
                            _log.debug('Echo received - clearing RX buffer')
                        self._rx_buffer = ''
                        parsing = AtParsingState.RESPONSE
                    else:
                        old_parsing = parsing
                        if self.serial.in_waiting == 0:
                            parsing = self._parsing_short(parsing)
                        else:
                            peeked = self._read()
                            if peeked == '*':
                                parsing = self._parsing_short()
                        if old_parsing != parsing:
                            result_ok = parsing == AtParsingState.OK
                else:
                    if parsing == AtParsingState.CRC and not crc_found:
                        if last == '*':
                            crc_found = True
                        else:
                            _log.warning('Unexpected CRC character %s', last)
            if parsing >= AtParsingState.OK:
                if vlog(VLOG_TAG):
                    _log.debug('Parsing complete')
                break
            if tick > 0 and self._rx_buffer == '':
                time.sleep(tick)
                countdown -= tick
                if vlog(VLOG_TAG):
                    _log.debug('Countdown: %d', countdown)
            time.sleep(self._char_delay)
        # end while < timeout
        if vlog(VLOG_TAG) and self._rx_buffer:
            _log.debug('Raw response: %s', dprint(self._rx_buffer))
        if parsing < AtParsingState.OK:
            _log.warning('AT command timeout during parsing')
            if self.verbose and self._rx_buffer.endswith('\r'):
                _log.info('Detected non-verbose - setting flag')
                self.verbose = False
            else:
                error = AtErrorCode.TIMEOUT
        elif parsing == AtParsingState.ERROR:
            error = AtErrorCode.ERROR
            if not self.crc and crc_found:
                _log.warning('CRC detected but not expected - setting flag')
                self.crc = True
                error = AtErrorCode.CRC_CONFIG_MISMATCH
            self._rx_buffer = ''
        else:
            if (self.crc):
                if vlog(VLOG_TAG):
                    _log.debug('Removing CRC')
                crc_length = 7
                if (self._rx_buffer[-crc_length:].startswith('*') and
                    self._rx_buffer[-crc_length:].endswith('\r\n')):
                    # CRC terminates response so remove it
                    self._rx_buffer = self._rx_buffer[:-crc_length]
                else:
                    _log.warning('CRC expected but not found - reset flag')
                    self.crc = False
            to_remove = VRES_OK if self.verbose else RES_OK
            self._rx_buffer = self._rx_buffer.replace(to_remove, '')
            if vlog(VLOG_TAG):
                _log.debug('Removed result code (%s): %s',
                           dprint(to_remove), dprint(self._rx_buffer))
            if prefix:
                self._rx_buffer = self._rx_buffer.replace(prefix, '', 1)
                if vlog(VLOG_TAG):
                    _log.debug('Removed prefix (%s): %s',
                               dprint(prefix), dprint(self._rx_buffer))
            self._rx_buffer = self._rx_buffer.strip()
            if vlog(VLOG_TAG):
                _log.debug('Trimmed leading/trailing whitespace: %s',
                           dprint(self._rx_buffer))
            self._rx_buffer = self._rx_buffer.replace('\r\n', '\n')
            self._rx_buffer = self._rx_buffer.replace('\n\n', '\n')
            if vlog(VLOG_TAG):
                _log.debug('Consolidated line feeds: %s',
                           dprint(self._rx_buffer))
        # cleanup
        self._pending_command = ''
        self.ready.set()
        return error
    
    def get_response(self) -> str:
        """Get the response following a read operation and clear the buffer."""
        response = self._rx_buffer
        self._rx_buffer = ''
        return response
    
    def read_line(self, read_until: str = '\r\n') -> str:
        """"""
        if vlog(VLOG_TAG) and not self.ready.is_set():
            _log.debug('Waiting for prior command/response completion')
        self.ready.wait()
        self.ready.clear()
        line: str = ''
        while self.serial.in_waiting > 0:
            line += self._read()
            if line.endswith(read_until) and len(line) > len(read_until):
                break
        self.ready.set()
        return line.strip()
    
    def _read(self) -> str:
        """Read an ASCII character or generate a warning."""
        char = self.serial.read()
        try:
            return char.decode()
        except UnicodeDecodeError as exc:
            _log.error('Unable to decode [%d] (%s)', char, exc)
            return ''
    
    def _parsing_ok(self) -> AtParsingState:
        """Internal helper for parsing valid response."""
        _log.debug('Result OK')
        if not self.crc:
            if 'CRC=1\r' in self._pending_command.upper():
                _log.debug('Command enabled CRC - set flag')
                self.crc = True
                return AtParsingState.CRC
        else:
            if 'CRC=0\r' in self._pending_command.upper():
                _log.debug('Command disabled CRC - reset flag')
                self.crc = False
            else:
                return AtParsingState.CRC
        return AtParsingState.OK
    
    def _parsing_error(self) -> AtParsingState:
        """Internal helper for parsing errored response."""
        _log.warning('Result ERROR')
        if self.crc or self.serial.in_waiting > 0:
            return AtParsingState.CRC
        else:
            time.sleep(self._char_delay)
            if self.serial.in_waiting > 0:
                return AtParsingState.CRC
        return AtParsingState.ERROR
    
    def _parsing_short(self, current: AtParsingState = None) -> AtParsingState:
        """Internal helper for parsing short code responses."""
        if vlog(VLOG_TAG):
            _log.debug('Check short response for: %s', dprint(self._rx_buffer))
        if (not self._rx_buffer.endswith((RES_OK, RES_ERR)) or
            (self.verbose and self._rx_buffer.startswith('\r\n'))):
            # just reading too fast, wait for next character
            return current
        if self.verbose:
            _log.warning('Clearing verbose flag due to short response match')
            self.verbose = False
        if self._rx_buffer.endswith(RES_OK):
            return self._parsing_ok()
        return self._parsing_error()
