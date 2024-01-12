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
ORPHAN_MAX_BYTES = 500

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
        self._orphaned: str = ''
        self._lock = threading.Lock()
    
    def is_data_waiting(self) -> bool:
        """Indicates if data is in the serial receive buffer."""
        return self.serial.in_waiting > 0
    
    def _update_orphaned(self, to_add: str, max_size: int = ORPHAN_MAX_BYTES):
        if len(self._orphaned) > max_size:
            _log.warning('Dumping orphaned data: %s', dprint(self._orphaned))
            self._orphaned = ''
        self._orphaned += to_add
    
    def read_rx_buffer(self,
                       read_until: str = '',
                       timeout: int = 0,
                       strip: bool = False,
                       ) -> 'str|None':
        """Reads data from the serial receive buffer.
        
        Args:
            timeout (int): Optional timeout in seconds to wait for data.
                If 0, will stop reading when no character is waiting.
        
        Returns:
            The data string if any was present, else `None`.
            
        """
        if not isinstance(timeout, int):
            timeout = 0
        with self._lock:
            self.serial.flush()   # wait for anything sent prior to be done
            rx = ''
            start_time = time.time()
            while (time.time() - start_time < timeout or timeout == 0):
                while (self.serial.in_waiting > 0):
                    rx += self._read()
                if ((read_until and rx.endswith(read_until) and
                     len(rx) > len(read_until)) or timeout == 0):
                    break
        if vlog(VLOG_TAG):
            if rx:
                _log.debug('Read from serial: %s', dprint(rx))
            else:
                _log.debug('No data waiting on serial buffer')
        return rx.strip() if strip else rx
    
    def send_at_command(self, at_command: str) -> None:
        """Submits an AT command to the NIMO modem to solicit a response.
        
        Must be followed by `read_at_response`.
        Use `get_response` to retrieve expected output (not OK or ERROR).
        
        Args:
            at_command: The command to send.
        
        """
        dump_buffer = self.read_rx_buffer()
        if self._lock.locked():
            _log.debug('%s waiting for pending command %s',
                       at_command, self._pending_command)
        self._lock.acquire()
        self._pending_command = at_command
        if self.crc and '*' not in at_command:
            self._pending_command = apply_crc(at_command)
        self._pending_command += '\r'
        self.serial.write(self._pending_command.encode())
        self.serial.flush()   # ensure it gets sent
        if dump_buffer:
            _log.warning('Orphaned RX buffer: %s (sending %s)',
                         dprint(dump_buffer), dprint(self._pending_command))
            self._update_orphaned(dump_buffer)
        if vlog(VLOG_TAG):
            _log.debug('Sent on serial: %s', dprint(self._pending_command))
    
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
                    if (parsing == AtParsingState.ECHO or
                        not self._rx_buffer.startswith('\r\n')):
                        xdata = self._rx_buffer.split('\n', 1)[0] + '\n'
                        _log.warning('Orphaned pre-command data: %s',
                                     dprint(xdata))
                        self._update_orphaned(xdata)
                        self._rx_buffer = self._rx_buffer.replace(xdata, '', 1)
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
                                error = AtErrorCode.INVALID_RESPONSE_CRC
                                result_ok = False
                    # else response line terminator - keep parsing
                elif last == '\r':
                    if self._rx_buffer.endswith(self._pending_command):
                        if self._rx_buffer != self._pending_command:
                            xdata = self._rx_buffer.replace(
                                self._pending_command, '')
                            _log.warning('Orphaned pre-command data: %s',
                                         dprint(xdata))
                            self._update_orphaned(xdata)
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
            if result_ok:
                if self.verbose and self._rx_buffer.endswith('\r'):
                    _log.info('Detected non-verbose - setting flag')
                    self.verbose = False
                elif self.crc and not crc_found:
                    _log.info('CRC expected but not found - clearing flag')
                    self.crc = False
                    error = AtErrorCode.CRC_CONFIG_MISMATCH
            else:
                _log.warning('AT command timeout during parsing')
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
                _log.debug('Removed result code: %s', dprint(self._rx_buffer))
            if prefix:
                self._rx_buffer = self._rx_buffer.replace(prefix, '', 1)
                if vlog(VLOG_TAG):
                    _log.debug('Removed prefix: %s', dprint(self._rx_buffer))
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
        if self._lock.locked():
            self._lock.release()
        return error
    
    def get_response(self) -> str:
        """Get the response following a read operation and clear the buffer."""
        response = self._rx_buffer
        self._rx_buffer = ''
        return response
    
    def _read(self) -> str:
        """Read an ASCII character or generate a warning."""
        char = self.serial.read()
        try:
            return char.decode()
        except UnicodeDecodeError as exc:
            _log.error('Discarding undecodable [%d] (%s)', ord(char), exc)
            return ''
    
    def _parsing_ok(self) -> AtParsingState:
        """Internal helper for parsing valid response."""
        if vlog(VLOG_TAG):
            _log.debug('Result OK for %s', dprint(self._pending_command))
        if not self.crc:
            if 'CRC=1\r' in self._pending_command.upper():
                _log.debug('%s enabled CRC - set flag', self._pending_command)
                self.crc = True
                return AtParsingState.CRC
        else:
            if ('CRC=0\r' in self._pending_command.upper() or
                ('Z' in self._pending_command.upper() and
                 not self.serial.in_waiting)):
                _log.debug('%s disabled CRC - reset flag', self._pending_command)
                self.crc = False
            else:
                return AtParsingState.CRC
        return AtParsingState.OK
    
    def _parsing_error(self) -> AtParsingState:
        """Internal helper for parsing errored response."""
        _log.warning('Result ERROR for: %s', dprint(self._pending_command))
        if self.crc or self.serial.in_waiting > 0:
            return AtParsingState.CRC
        else:
            time.sleep(self._char_delay)
            if self.serial.in_waiting > 0:
                return AtParsingState.CRC
        return AtParsingState.ERROR
    
    def _parsing_short(self, current: AtParsingState = None) -> AtParsingState:
        """Internal helper for parsing short code responses."""
        if (self._rx_buffer.startswith('\r\n') or
            not self._rx_buffer.endswith((RES_OK, RES_ERR))):
            # just read too fast, keep parsing
            return current
        if self._rx_buffer.endswith((RES_OK, RES_ERR)):
            # check if it's really a response code or part of data
            rc = RES_OK if self._rx_buffer.endswith(RES_OK) else RES_ERR
            if ('\r\n' in self._rx_buffer and
                self._rx_buffer.split('\r\n')[-1] != rc):
                # doesn't actually end in a result code, keep parsing
                return current
        if self.verbose:
            _log.warning('Clearing verbose flag due to short response: %s',
                         dprint(self._rx_buffer))
            self.verbose = False
        if self._rx_buffer.endswith(RES_OK):
            return self._parsing_ok()
        return self._parsing_error()

    def get_ophaned(self) -> str:
        """Gets orphaned data and clears the orphaned buffer"""
        orphaned = self._orphaned
        self._orphaned = ''
        return orphaned
