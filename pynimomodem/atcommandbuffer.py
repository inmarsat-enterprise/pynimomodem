import logging
import threading
import time

from serial import Serial

from .crcxmodem import apply_crc, validate_crc
from .helpers import dprint, vlog
from .nimoconstants import AtErrorCode, AtParsingState

VLOG_TAG = 'atcommand'
DEFAULT_AT_TIMEOUT = 3   # seconds
VRES_OK = '\r\nOK\r\n'
VRES_ERR = '\r\nERROR\r\n'
RES_OK = '0\r'
RES_ERR = '4\r'

_log = logging.getLogger(__name__)


class AtCommandBuffer:
    def __init__(self, serial: Serial) -> None:
        self.echo: bool = True
        self.verbose: bool = True
        self.quiet: bool = False
        self.crc: bool = False
        if not isinstance(serial, Serial):
            raise ValueError('Invalid serial port')
        self.serial = serial
        self._char_delay: float = 8 / serial.baudrate
        self._pending_command: str = None
        self._rx_buffer: str = ''
        self.ready = threading.Event()
        self.ready.set()
    
    def send_at_command(self, at_command: str) -> None:
        """Submits an AT command to the NIMO modem to solicit a response.
        
        Use `read_at_response` then `get_resopnse` after sending the command.
        
        Args:
            at_command: The command to send.
        
        """
        self.ready.wait()
        self.ready.clear()
        self.serial.flush()   # wait for anything sent prior to be done
        dump_buffer = ''
        while self.serial.in_waiting > 0:
            dump_buffer += self.serial.read().decode()
        if dump_buffer:
            _log.warning('Dumping RX buffer: %s', dprint(dump_buffer))
        self._pending_command = at_command
        if self.crc and '*' not in at_command:
            self._pending_command = apply_crc(at_command)
        self._pending_command += '\r'
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
                    self._rx_buffer += self.serial.read().decode()
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
                            peeked = self.serial.read().decode()
                            if peeked == '*':
                                parsing = self._parsing_short()
                        if old_parsing != parsing:
                            result_ok = parsing == AtParsingState.OK
                else:
                    if parsing == AtParsingState.CRC and last == '*':
                        crc_found = True
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
        if parsing < AtParsingState.OK:
            _log.warning('AT command timeout during parsing')
            if self.verbose and self._rx_buffer.endswith('\r'):
                _log.info('Detected non-verbose - setting flag')
                self.verbose = False
            else:
                error = AtErrorCode.TIMEOUT
        elif parsing == AtParsingState.ERROR:
            if not self.crc and crc_found:
                _log.warning('CRC detected but not expected - setting flag')
                self.crc = True
                error = AtErrorCode.CRC_CONFIG_MISMATCH
            self._rx_buffer = ''
        else:
            if (self.crc):
                if vlog(VLOG_TAG):
                    _log.debug('Removing CRC')
                crc_length = len('*ABCD\r\n')
                self._rx_buffer = self._rx_buffer[:-crc_length]
            if vlog(VLOG_TAG):
                _log.debug('Removing result code')
            to_remove = VRES_OK if self.verbose else RES_OK
            self._rx_buffer = self._rx_buffer.replace(to_remove, '')
            if prefix:
                if vlog(VLOG_TAG):
                    _log.debug('Removing prefix: %s', prefix)
                self._rx_buffer = self._rx_buffer.replace(prefix, '', 1)
            self._rx_buffer = self._rx_buffer.strip()
            if vlog(VLOG_TAG):
                _log.debug('Consolidating line feeds')
            self._rx_buffer = self._rx_buffer.replace('\r\n', '\n')
            self._rx_buffer = self._rx_buffer.replace('\n\n', '\n')
        # cleanup
        self._pending_command = ''
        self.ready.set()
        return error
    
    def get_response(self) -> str:
        """Get the response following a read operation and clear the buffer."""
        response = self._rx_buffer
        self._rx_buffer = ''
        return response
    
    def get_urc(self) -> 'int|None':
        """Get the (next) Unsolicited Response Code if present.
        
        Returns:
            An integer code if present, or `None`.
        
        """
        self.ready.wait()
        urc_buffer: str = ''
        prefix = '+QURC:'
        while self.serial.in_waiting > 0:
            urc_buffer += self.serial.read().decode()
            last = urc_buffer[-1]
            if last == '\n':
                if urc_buffer.strip().startswith(prefix):
                    urc = int(urc_buffer.replace(prefix, '').strip())
                    if vlog(VLOG_TAG):
                        _log.debug('Found URC: %d', urc)
                    return urc
    
    def _parsing_ok(self) -> AtParsingState:
        """Internal helper for parsing valid response."""
        if self.crc or self._pending_command.endswith('CRC=1\r'):
            self.crc = True
            return AtParsingState.CRC
        return AtParsingState.OK
    
    def _parsing_error(self) -> AtParsingState:
        """Internal helper for parsing errored response."""
        _log.warning('Parsing error')
        if self.crc or self.serial.in_waiting > 0:
            return AtParsingState.CRC
        else:
            time.sleep(self._char_delay)
            if self.serial.in_waiting > 0:
                return AtParsingState.CRC
        return AtParsingState.ERROR
    
    def _parsing_short(self, current: AtParsingState = None) -> AtParsingState:
        """Internal helper for parsing short code responses."""
        if self._rx_buffer.endswith(RES_OK):
            self.verbose = False
            return self._parsing_ok()
        elif self._rx_buffer.endswith(RES_ERR):
            self.verbose = False
            return self._parsing_error()
        return current
