"""Class for a Non-IP Modem using Orbcomm network protocols.

This module encapsulates specific AT commands from the following supported
NIMO modem manufacturers:

* **ORBCOMM**
* **Quectel**

Key concepts include modem properties, configuration, and satellite acquisition
details including signal level.

"""
import base64
import logging
import time
from dataclasses import dataclass
from enum import IntEnum
from threading import Event

from serial import Serial

from .atcommandbuffer import DEFAULT_AT_TIMEOUT, AtCommandBuffer
from .constants import (
    BAUDRATES,
    MSG_MO_MAX_SIZE,
    MSG_MO_NAME_MAX_LEN,
    MSG_MO_NAME_QMAX_LEN,
    AtErrorCode,
    BeamState,
    ControlState,
    DataFormat,
    GeoBeam,
    GnssMode,
    GnssModeOrbcomm,
    GnssModeQuectel,
    MessagePriority,
    MessageState,
    NetworkStatus,
    PowerMode,
    SignalLevelRegional,
    SignalQuality,
    UrcCode,
    WakeupPeriod,
    WakeupWay,
    WorkMode,
)
from .location import (
    ModemLocation,
    SatelliteLocation,
    get_location_from_nmea_data,
    get_satellite_location,
)
from .message import MoMessage, MtMessage, NimoMessage
from .nimoutils import iso_to_ts, vlog

VLOG_TAG = 'nimomodem'

_log = logging.getLogger(__name__)


class Manufacturer(IntEnum):
    """Supported NIMO modem implementations."""
    NONE = 0
    ORBCOMM = 1
    QUECTEL = 2


@dataclass
class AcquisitionInfo:
    """Details about the satellite acquisition state of the modem.
    
    Attributes:
        ctrl_state (ControlState): Primary network acquisition state.
        beam_state (BeamState): Secondary beam acquistion state.
        rssi (float): Signal indicator Carrier to Noise ratio (dB-Hz).
        vcid (int): Virtual carrier identifier for low-level sanity check.
    
    """
    ctrl_state: ControlState = ControlState.STOPPED
    beam_state: BeamState = BeamState.IDLE
    rssi: float = 0.0
    vcid: int = 0


class ModemError(Exception):
    """Base class for NIMO modem errors."""


class ModemTimeout(ModemError):
    """Serial response timeout."""


class ModemCrcConfig(ModemError):
    """Request/response mismatch of CRC presence."""


class ModemAtError(ModemError):
    """AT command related errors with error_code property."""
    @property
    def error_code(self) -> AtErrorCode:
        return AtErrorCode[self.args[0]]


class NimoModem:
    """A class for NIMO satellite IoT modem interaction."""
    # __slots__ = ('_modem', '_mobile_id',
    #              '_mfr_code', '_modem_booted', '_ready',
    #              )
    
    def __init__(self, serial_port: str, **kwargs) -> None:
        """Instantiate the NimoModem object.
        
        For additional kwargs see PySerial API:
        https://pyserial.readthedocs.io/en/latest/pyserial_api.html
        
        Args:
            serial_port (str): The path to the modem's serial port.
        
        Keyword Args:
            baudrate (int): The baud rate of the modem (default 9600)
        
        Raises:
            `ConnectionError` if unable to connect to the serial port.
        
        """
        try:
            self._serial = Serial(serial_port, **kwargs)
        except Exception as exc:
            raise ConnectionError('Unable to connect to serial') from exc
        self._modem: AtCommandBuffer = AtCommandBuffer(self._serial)
        self._baudrate: int = self._serial.baudrate
        self._is_connected: bool = False
        self._modem_booted: bool = False
        self._mobile_id: str = ''
        self._manufacturer: Manufacturer = Manufacturer.NONE
        self._ready = Event()
        self._ready.set()
    
    @property
    def is_ready(self) -> bool:
        return self._ready.is_set()
    
    @property
    def crc_enabled(self) -> bool:
        return self._modem.crc
    
    @property
    def modem_booted(self) -> bool:
        return self._modem_booted
    
    @property
    def _mfr(self) -> Manufacturer:
        """Used internally to support different manufacturer commands."""
        if not self._manufacturer:
            self.get_manufacturer()
        return self._manufacturer
    
    @property
    def _mo_msg_name_len_max(self) -> int:
        """Used internally to restrict the length of the MO message name."""
        maxlen = MSG_MO_NAME_MAX_LEN
        if self._mfr == Manufacturer.QUECTEL:
            maxlen = MSG_MO_NAME_QMAX_LEN
        return maxlen
    
    def _at_command_response(self,
                             command: str,
                             prefix: str = '',
                             timeout: int = DEFAULT_AT_TIMEOUT) -> str:
        """Send a command and return the response.
        
        Blocks until response has been received.
        
        Args:
            command (str): The AT command to send.
            prefix (str): Optional prefix to remove from response.
            timeout (int): Maximum time in seconds to wait for response.
        
        Raises:
            `ModemTimeout` if no response is received.
            `ModemCrcConfig` if CRC is not used on both request/response.
            `ModemAtError` for other cases of errored response.
        
        """
        self._ready.wait()
        self._ready.clear()
        try:
            self._modem.send_at_command(command)
            err = self._modem.read_at_response(prefix, timeout)
            if err == AtErrorCode.OK:
                return self._modem.get_response()
            elif err == AtErrorCode.TIMEOUT:
                raise ModemTimeout
            elif err == AtErrorCode.CRC_CONFIG_MISMATCH:
                raise ModemCrcConfig
            else:
                err = self.get_last_error_code()
                raise ModemAtError(err.name)
        finally:
            self._ready.set()
    
    def connect(self) -> None:
        """Attach to the modem via serial communications.
        
        Provided for backward compatibility. Connection is usually automatic
        when instantiating `NimoModem`.
        
        """
        if not self._serial.is_open:
            self._serial.open()
    
    def disconnect(self) -> None:
        """Detach from the modem serial communications.
        
        Provided for backward compatibility. Not typically required.
        
        """
        self._is_connected = False
        self._modem_booted = False
        if self._serial.is_open:
            self._serial.close()
    
    def is_connected(self) -> bool:
        """Indicates if the modem is responding to a basic AT query."""
        try:
            self._at_command_response('AT')
            self._is_connected = True
            self._modem_booted = True
            return True
        except ModemError:
            self._is_connected = False
            self._modem_booted = False
            return False
    
    @property
    def baudrate(self) -> int:
        """The baudrate of the serial connection."""
        return self._modem.serial.baudrate
    
    @baudrate.setter
    def baudrate(self, baudrate: int):
        """Set the baud rate of the modem and adjust the serial rate."""
        if baudrate not in [9600, 115200]:
            raise ValueError('Invalid baudrate')
        self._at_command_response(f'AT+IPR={baudrate}')
        self._modem.serial.baudrate = baudrate
    
    def retry_baudrate(self) -> bool:
        """"""
        for baud in BAUDRATES:
            self._modem.serial.baudrate = baud
            if self.is_connected():
                return True
        return False
    
    def await_boot(self, boot_timeout: int = 10) -> bool:
        """Indicates if a boot string is received within a timeout window.
        
        Use `is_connected` before waiting for boot.
        
        Args:
            boot_timeout (int): The maximum time to wait in seconds.
        
        Returns:
            True if a valid boot string was received inside the timeout.
        
        """
        boot_strings = ['ST Version', 'RDY']
        _log.debug('Awaiting modem boot string for %d seconds...', boot_timeout)
        rx_data = ''
        started = time.time()
        while time.time() - started < boot_timeout and not self._modem_booted:
            while self._modem.is_data_waiting():
                rx_data += self._modem.read_rx_buffer()
            if rx_data and any(b in rx_data for b in boot_strings):
                self._modem_booted = True
                _log.debug('Found boot string - clearing Rx buffer')
                while self._modem.is_data_waiting():
                    rx_data += self._modem.read_rx_buffer()
                break
        return self._modem_booted
    
    def get_last_error_code(self) -> AtErrorCode:
        """Get the last error code from the modem."""
        return AtErrorCode(int(self._at_command_response('ATS80?')))
    
    def initialize(self,
                   echo: bool = True,
                   verbose: bool = True,
                   ) -> bool:
        """Initialize the modem AT configuration for Echo and Verbose."""
        at_command = (f'ATZ;E{int(echo)};V{int(verbose)}')
        try:
            self._at_command_response(at_command)
            return True
        except ModemAtError as exc:
            if exc.error_code == AtErrorCode.CRC_CONFIG_MISMATCH:
                _log.info('Attempting re-initialize with CRC enabled')
                self._at_command_response(at_command)
                return True
            raise
    
    def set_crc(self, enable: bool = False) -> bool:
        """Enable or disable CRC error checking on the modem serial port."""
        try:
            self._at_command_response(f'AT%CRC={int(enable)}')
            return True
        except ModemCrcConfig:
            if ((self._modem.crc and enable) or
                (not self._modem.crc and not enable)):
                return True
            return False
    
    def reset_factory_config(self) -> None:
        """Reset the modem's factory default configuration."""
        self._at_command_response('AT&F')
    
    def save_config(self) -> None:
        """Store the current configuration to modem non-volatile memory."""
        self._at_command_response('AT&W')
    
    def get_mobile_id(self) -> str:
        """Get the modem's globally unique identifier."""
        if not self._mobile_id:
            try:
                self._mobile_id = self._at_command_response('AT+GSN', '+GSN:')
                if vlog(VLOG_TAG):
                    _log.debug('Cached Mobile ID %s', self._mobile_id)
            except ModemError:
                self._mobile_id = ''
                raise
        return self._mobile_id
    
    @property
    def _is_simulator(self) -> bool:
        return self.get_mobile_id().startswith('00000000')
    
    def get_manufacturer(self) -> str:
        """Get the manufacturer name."""
        if not self._manufacturer:
            try:
                mfr = self._at_command_response('ATI')
                if 'quectel' in mfr.lower():
                    self._manufacturer = Manufacturer.QUECTEL
                else:
                    if not any(m in mfr.lower()
                               for m in ['orbcomm', 'skywave']):
                        _log.warning('Unsupported manufacturer %s', mfr)
                    self._manufacturer = Manufacturer.ORBCOMM
                if vlog(VLOG_TAG):
                    _log.debug('Caching manufacturer: %s',
                               self._manufacturer.name)
            except ModemError:
                self._manufacturer = Manufacturer.NONE
                raise
        return self._manufacturer.name
    
    def get_model(self) -> str:
        """Get the manufacturer model name."""
        cmd = 'ATI4'
        if self._mfr == Manufacturer.QUECTEL:
            cmd = 'ATI'
        try:
            response = self._at_command_response(cmd)
            if response:
                if self._mfr == Manufacturer.QUECTEL:
                    response = response.split('\n')[1]
            return response
        except ModemError:
            return ''
    
    def get_firmware_version(self) -> str:
        """Get the modem's firmware version."""
        # TODO: Firmware structure with hardware, firmware, software?
        return self._at_command_response('AT+GMR', '+GMR:')
    
    def get_system_time(self) -> int:
        """Get the system/GNSS time from the modem."""
        try:
            nimo_time = self._at_command_response('AT%UTC', '%UTC:')
            iso_time = nimo_time.replace(' ', 'T') + 'Z'
            return iso_to_ts(iso_time)
        except ModemError:
            return 0
    
    def get_temperature(self) -> 'int|None':
        """Get the processor temperature in Celsius."""
        return int(int(self._at_command_response('ATS85?')) / 10)
    
    def is_transmit_allowed(self) -> bool:
        """Indicates if the modem is able to transmit data."""
        return self.get_network_status() == 5
    
    def is_blocked(self) -> bool:
        """Indicates if line-of-sight to the satellite is blocked."""
        return self.get_network_status() == 8
    
    def is_muted(self) -> bool:
        """Indicates if the modem has been muted (disallowed to transmit data).
        """
        return self.get_network_status() == 7
    
    def is_updating_network(self) -> bool:
        """Indicates if the modem is updating network information.
        
        The modem should not be powered down during a network update.
        
        """
        return self.get_network_status() == 4
    
    def get_network_status(self) -> NetworkStatus:
        """Get the current satellite acquisition status."""
        cmd = 'ATS54?'
        prefix = ''
        if self._mfr == Manufacturer.QUECTEL:
            cmd = 'AT+QREG?'
            prefix = '+QREG:'
        return NetworkStatus(int(self._at_command_response(cmd, prefix)))
    
    def get_rssi(self) -> float:
        """Get the current Received Signal Strength Indicator.
        
        Also referred to as SNR or C/N0 (dB-Hz)
        
        """
        cmd = 'ATS90=3 S91=1 S92=1 S116?'
        prefix = ''
        if self._mfr == Manufacturer.QUECTEL:
            cmd = 'AT+QSCN'
            prefix = '+QSCN:'
        return int(self._at_command_response(cmd, prefix)) / 100
    
    def get_signal_quality(self) -> SignalQuality:
        """Get a qualitative indicator from 0..5 of the satellite signal."""
        snr = self.get_rssi()
        if snr >= SignalLevelRegional.INVALID.value:
            return SignalQuality.WARNING
        if snr >= SignalLevelRegional.BARS_5.value:
            return SignalQuality.STRONG
        if snr >= SignalLevelRegional.BARS_4.value:
            return SignalQuality.GOOD
        if snr >= SignalLevelRegional.BARS_3.value:
            return SignalQuality.MID
        if snr >= SignalLevelRegional.BARS_2.value:
            return SignalQuality.LOW
        if snr >= SignalLevelRegional.BARS_1.value:
            return SignalQuality.WEAK
        return SignalQuality.NONE
    
    def get_acquisition_detail(self) -> AcquisitionInfo:
        """Get the detailed satellite acquisition status.
        
        Includes `acquisition_state`, `beamsearch_state`, `vcid` and `snr`
        indicators.
        
        """
        cmd = 'ATS90=3 S91=1 S92=1 S122? S123? S116? S101?'
        prefix = ''
        if self._mfr == Manufacturer.QUECTEL:
            cmd = 'AT+QEVNT=3,1'
            prefix = '+QEVNT:'
        result_str = self._at_command_response(cmd, prefix, timeout=10)
        if self._mfr == Manufacturer.ORBCOMM:
            results = [int(x) for x in result_str.split('\n')]
            ctrl_state = ControlState(results[0])
            beam_state = BeamState(results[1])
            rssi = float(results[2]) / 100
            vcid = results[3]
        elif self._mfr == Manufacturer.QUECTEL:
            # Workaround Quectel 20230731 documentation error says +QEVNT:
            result_str = result_str.replace('+QEVENT:', '').strip()
            results = [int(x) for x in result_str.split(',')]
            # <dataCount>,<signedBitmask>,<MTID>,<timestamp>,
            #   <class>,<subclass>,<priority>,<data0>,...
            data0 = 7   # list index where trace data starts
            ctrl_state = ControlState(results[data0+22])
            beam_state = BeamState(results[data0+23])
            rssi = float(results[data0+16]) / 100
            vcid = results[data0+1]
        return AcquisitionInfo(ctrl_state, beam_state, rssi, vcid)
    
    def send_data(self, data: bytes, **kwargs) -> 'str|MoMessage':
        """Submits data to send as a mobile-originated message.
        
        If a `message_name` is not supplied one will be generated using the
        least significant 8 digits of unix timestamp.
        
        Args:
            data (bytes): The data to send.
        
        Keyword Args:
            message_name (str): Optional handle for message in Tx queue. Max 8
                characters for Orbcomm modem or 12 for Quectel.
            priority (int): Optional priority 1 (highest) .. 4 (low, default).
                May use `MessagePriority`.
            codec_sin (int): Optional first byte of payload to add as a codec
                service identifier, must be in range 16..255.
            codec_min (int): Optional second byte of payload to add as a codec
                message identifier, must be in range 0..255.
            return_message (bool): If set, returns a `MoMessage` instead of the
                message handle.
        
        Returns:
            Message handle (str) or `MoMessage` if `return_message` kwarg is set.
        
        Raises:
            `ValueError` for various parameter limit violations.
        
        """
        data_size = len(data)
        msg_payload_sin_min = b''
        message_name = kwargs.get('message_name', '')
        priority = MessagePriority(kwargs.get('priority',
                                              MessagePriority.LOW.value))
        codec_sin = kwargs.get('codec_sin', -1)
        codec_min = kwargs.get('codec_min', -1)
        if codec_sin > -1:
            data_size += 1
            msg_payload_sin_min += codec_sin.to_bytes(1, 'big')
        if codec_min > -1:
            data_size += 1
            msg_payload_sin_min += codec_min.to_bytes(1, 'big')
        if not 2 <= data_size <= MSG_MO_MAX_SIZE:
            raise ValueError('Invalid mobile-originated message size')
        if message_name and len(message_name) > self._mo_msg_name_len_max:
            raise ValueError('Message name too long')
        data_index = 0
        if codec_sin <= -1:
            codec_sin = data[0]
            data_index += 1
            data_size -= 1
        if codec_sin not in range(16, 256):
            raise ValueError('Illegal first payload byte SIN must be 16..255')
        if codec_min <= -1:
            codec_min = data[1]
            data_index += 1
            data_size -= 1
        if codec_min > 255:
            raise ValueError('Invalid second payload byte MIN must be 0..255')
        max_name_len = self._mo_msg_name_len_max
        if message_name and len(message_name) > max_name_len:
            raise ValueError(f'Invalid message name longer than {max_name_len}')
        if len(message_name) == 0:
            message_name = f'{int(time.time())}'[-max_name_len:]
        # Convert to base64 string for serial efficiency
        #   no effect on OTA size, modem always decodes and sends raw bytes OTA
        data_format = DataFormat.BASE64
        formatted_data = base64.b64encode(data[2:]).decode('utf-8')
        cmd = 'AT%MGRT='
        codec_sep = '.'
        if self._mfr == Manufacturer.QUECTEL:
            cmd = 'AT+QSMGT='
            codec_sep = ','
        cmd = (f'{cmd}"{message_name}",{priority},{codec_sin}{codec_sep}'
               f'{codec_min},{data_format},{formatted_data}')
        self._at_command_response(cmd)
        if kwargs.get('return_message', False) is True:
            return MoMessage(message_name, priority, MessageState.TX_READY,
                                payload=(msg_payload_sin_min + data))
        return message_name
    
    def send_text(self, text: str, **kwargs) -> 'str|MoMessage':
        """Submits a text string to send as data.
        
        If `codec_sin` kwarg is not provided 128 is prepended as the first byte.
        If `codec_min` kwarg is not provided 1 is prepended as the second byte.
        Other kwargs as per `send_data`.
        
        Args:
            text (str): The text message to send.
        
        Returns:
            (str) The message name assigned or MoMessage if kwarg
                `return_message` is set.
        
        """
        data = b''
        codec_sin = int(kwargs.get('codec_sin', 128))
        data += codec_sin.to_bytes(1, 'big')
        codec_min = int(kwargs.get('codec_min', 1))
        data += codec_min.to_bytes(1, 'big')
        data += text.encode()
        flowthru = ['message_name', 'priority', 'return_message']
        next_kwargs = { k:v for k, v in kwargs if k in flowthru }
        return self.send_data(data, **next_kwargs)
    
    def cancel_mo_message(self, message_name: str) -> bool:
        """Attempts to cancel a previously submitted mobile-originated message.
        
        Args:
            message_name (str): The mobile-originated message handle to delete.
        
        """
        _log.debug('Attempting to cancel MO message %s', message_name)
        cmd = 'AT%MGRC'
        if self._mfr == Manufacturer.QUECTEL:
            cmd = 'AT+QSMGC'
        cmd += f'="{message_name}"'
        self._at_command_response(cmd)
        message_states = self.get_mo_message_states(message_name)
        if len(message_states) > 0:
            state = message_states[0].state
            if state == MessageState.TX_CANCELLED:
                return True
        elif self._is_simulator:
            return True
        _log.warn('Failed to cancel message %s', message_name)
        return False
    
    def get_mo_message_states(self, message_name: str = '') -> 'list[MoMessage]':
        """Get a list of mobile-originated message states in the modem Tx queue.
        
        Args:
            message_name (str): Optional filter on message name.
        
        Returns:
            A list of `MoMessage` objects including state and metadata.
        
        """
        cmd = 'AT%MGRS'
        prefix = '%MGRS:'
        if self._mfr == Manufacturer.QUECTEL:
            cmd = 'AT+QSMGS'
            prefix = '+QSMGS:'
        if message_name and not self._is_simulator:
            # Orbcomm Modem Simulator returns ERROR for %MGRS= command
            cmd += f'="{message_name}"'
        response_str = self._at_command_response(cmd, prefix)
        return self._parse_message_states(response_str, is_mo=True)
    
    def _parse_message_states(self,
                              response_str: str,
                              is_mo: bool,
                              ) -> 'list[NimoMessage]':
        """Parses textual metadata to build a SatelliteMessageState."""
        mo_states = []
        if not response_str:
            return mo_states
        if vlog(VLOG_TAG):
            _log.debug('Parsing %s message states from %s',
                       'MO' if is_mo else 'MT', response_str)
        states_meta = [m for m in response_str.split('\n') if m != '']
        for meta in states_meta:
            message = MoMessage() if is_mo else MtMessage()
            for field_idx, field_data in enumerate(meta.split(',')):
                self._update_message_state(message, field_idx,
                                           field_data, is_mo)
            mo_states.append(message)
        return mo_states
    
    def _update_message_state(self,
                              message_state: NimoMessage,
                              field_idx: int,
                              field_data: str,
                              is_mo: bool) -> None:
        """Parse textual metadata to update a message's state."""
        if vlog(VLOG_TAG):
            _log.debug('Parsing %s message state index %d: %s',
                       'MO' if is_mo else 'MT', field_idx, field_data)
        mfr = self._mfr
        if field_idx == 0:
            message_state.name = field_data.replace('"', '')
            if vlog(VLOG_TAG):
                _log.debug('Message name: %s', message_state.name)
        elif field_idx == 1 and mfr == Manufacturer.ORBCOMM:
            if vlog(VLOG_TAG):
                _log.debug('Ignoring msgNum %s', field_data)
        elif ((field_idx == 2 and mfr == Manufacturer.ORBCOMM) or
              (field_idx == 1 and mfr == Manufacturer.QUECTEL)):
            message_state.priority = MessagePriority(int(field_data))
            if vlog(VLOG_TAG):
                _log.debug('Message priority %s', message_state.priority.name)
        elif ((field_idx == 3 and mfr == Manufacturer.ORBCOMM) or
              (field_idx == 2 and mfr == Manufacturer.QUECTEL)):
            if vlog(VLOG_TAG):
                _log.debug('Ignoring codec SIN %s', field_data)
        elif ((field_idx == 4 and mfr == Manufacturer.ORBCOMM) or
              (field_idx == 3 and mfr == Manufacturer.QUECTEL)):
            message_state.state = MessageState(int(field_data))
            _log.debug('Message state: %s', message_state.state.name)
        elif ((field_idx == 5 and mfr == Manufacturer.ORBCOMM) or
              (field_idx == 4 and mfr == Manufacturer.QUECTEL)):
            message_state.length = int(field_data)
            _log.debug('Message size: %d bytes', message_state.length)
        elif ((field_idx == 6 and mfr == Manufacturer.ORBCOMM) or
              (field_idx == 5 and mfr == Manufacturer.QUECTEL)):
            message_state.bytes_delivered = int(field_data)
            _log.debug('Bytes delivered: %d', message_state.bytes_delivered)
        else:
            _log.warning('Unhandled field index %d (%s) for manufacturer %s',
                         field_idx, 'MO' if is_mo else 'MT', mfr.name)
    
    def get_mt_message_states(self, message_name: str = '') -> 'list[MtMessage]':
        """Get a list of mobile-terminated message states in the modem Tx queue.
        
        Args:
            message_name (str): Optional filter on message name.
        
        Returns:
            A list of `MtMessage` objects including state and metadata.
        
        """
        cmd = 'AT%MGFN' if not message_name else 'AT%MGFS'
        prefix = '%MGFN:' if not message_name else 'AT%MGFS:'
        if self._mfr == Manufacturer.QUECTEL:
            cmd = 'AT+QRMGN' if not message_name else 'AT+QRMGS'
            prefix = '+QRMGN:' if not message_name else '+QRMGS:'
        if message_name and not self._is_simulator:
            cmd += f'="{message_name}"'
        response_str = self._at_command_response(cmd, prefix)
        return self._parse_message_states(response_str, is_mo=False)
    
    def get_mt_message(self, message_name: str) -> 'MtMessage|None':
        """Get a mobile-terminated message from the modem's Rx queue by name."""
        cmd = 'AT%MGFG'
        prefix = '%MGFG:'
        if self._mfr == Manufacturer.QUECTEL:
            cmd = 'AT+GRMGR'
            prefix = '+GRMGR:'
        data_format = DataFormat.BASE64
        cmd += f'="{message_name}",{data_format}'
        response = self._at_command_response(cmd, prefix)
        if response:
            return self._parse_mt_message(response)
        return None
    
    def _parse_mt_message(self, meta: str) -> MtMessage:
        """Parse textual metadata to build a MtMessage."""
        if vlog(VLOG_TAG):
            _log.debug('Parsing MT message from meta: %s', meta)
        data_includes_sin = False
        mfr = self._mfr
        message = MtMessage()
        for field_idx, field_data in enumerate(meta.split(',')):
            if field_idx == 0:
                message.name = field_data.replace('"', '')
                if vlog(VLOG_TAG):
                    _log.debug('Message name: %s', message.name)
            elif (field_idx == 1 and mfr == Manufacturer.ORBCOMM):
                if vlog(VLOG_TAG):
                    _log.debug('Ignoring msgNum %s', field_data)
            elif (field_idx == 2 and mfr == Manufacturer.ORBCOMM):
                message.priority = MessagePriority(int(field_data))
                if vlog(VLOG_TAG):
                    _log.debug('Message priority %s', message.priority.name)
            elif ((field_idx == 3 and mfr == Manufacturer.ORBCOMM) or
                  (field_idx == 1 and mfr == Manufacturer.QUECTEL)):
                codec_sin = int(field_data)
                if not data_includes_sin:
                    message.payload += codec_sin.to_bytes(1, 'big')
                if vlog(VLOG_TAG):
                    _log.debug('Added SIN as first payload byte: %d', codec_sin)
            elif (field_idx == 4 and mfr == Manufacturer.ORBCOMM):
                message.state = MessageState(int(field_data))
                if vlog(VLOG_TAG):
                    _log.debug('Message state %s', message.state.name)
            elif ((field_idx == 5 and mfr == Manufacturer.ORBCOMM) or
                  (field_idx == 2 and mfr == Manufacturer.QUECTEL)):
                message.length = int(field_data)
                if vlog(VLOG_TAG):
                    _log.debug('Message size: %d bytes', message.length)
            elif ((field_idx == 6 and mfr == Manufacturer.ORBCOMM) or
                  (field_idx == 3 and mfr == Manufacturer.QUECTEL)):
                data_format = DataFormat(int(field_data))
                if vlog(VLOG_TAG):
                    _log.debug('Data format %s', data_format.name)
            elif ((field_idx == 7 and mfr == Manufacturer.ORBCOMM) or
                  (field_idx == 4 and mfr == Manufacturer.QUECTEL)):
                if vlog(VLOG_TAG):
                    _log.debug('Decoding payload from: %s', field_data)
                if message.length > 0:
                    if data_format == DataFormat.BASE64:
                        message.payload += base64.b64decode(field_data)
                    elif data_format == DataFormat.HEX:
                        message.payload += bytes.fromhex(field_data)
                    else:   # DataFormat.TEXT
                        message.payload += field_data.encode()
                    if message.length != len(message.payload):
                        _log.warn('Message length mismatch')
        return message
    
    def delete_mt_message(self, message_name: str) -> bool:
        """Remove a mobile-terminated message from the modem's Rx queue."""
        cmd = 'AT%MGFM'
        if self._mfr == Manufacturer.QUECTEL:
            cmd = 'AT+QRMGM'
        cmd += f'="{message_name}"'
        self._at_command_response(cmd)
        check = self.get_mt_message_states(message_name)
        if check and check[0].state == MessageState.RX_RETRIEVED:
            return True
        return False
    
    def receive_data(self, message_name: str) -> 'bytes|None':
        """Get the raw data from a mobile-terminated message."""
        message = self.get_mt_message(message_name)
        if message:
            return message.payload
        return None
    
    def get_gnss_mode(self) -> GnssMode:
        """Get the modem's GNSS receiver mode."""
        cmd = 'ATS39?'
        prefix = ''
        if self._mfr == Manufacturer.QUECTEL:
            cmd = 'AT+QGNSSMOD?'
            prefix = '+QGNSSMOD:'
        response = self._at_command_response(cmd, prefix)
        if self._mfr == Manufacturer.QUECTEL:
            return GnssModeQuectel(int(response))
        return GnssModeOrbcomm(int(response))
    
    def set_gnss_mode(self, gnss_mode: GnssMode) -> None:
        """Get the modem's GNSS receiver mode."""
        cmd = f'ATS39={gnss_mode}'
        prefix = ''
        if self._mfr == Manufacturer.QUECTEL:
            if not GnssModeQuectel.is_valid(gnss_mode):
                raise ValueError('Invalid GNSS mode')
            cmd = f'AT+QGNSSMOD={gnss_mode}'
            prefix = '+QGNSSMOD:'
        else:
            if not GnssModeOrbcomm.is_valid(gnss_mode):
                raise ValueError('Invalid GNSS mode')
        self._at_command_response(cmd, prefix)
    
    def get_gnss_continuous(self) -> int:
        """Get the modem's GNSS continuous refresh interval in seconds."""
        cmd = 'ATS55?'
        prefix = ''
        if self._mfr == Manufacturer.QUECTEL:
            cmd = 'AT+QGNSSCW?'
            prefix = '+QGNSSCW:'
        return int(self._at_command_response(cmd, prefix))
    
    def set_gnss_continuous(self, interval: int) -> None:
        """Set the modem's GNSS continuous refresh interval in seconds.
        
        Args:
            interval (int): Automatic update interval 0..30 seconds.
        
        Returns:
            `True` if successful.
        
        Raises:
            `ValueError` if invalid interval is specified.
        
        """
        if interval not in range (0, 31):
            raise ValueError('Invalid GNSS refresh interval')
        cmd = f'ATS55={interval}'
        if self._mfr == Manufacturer.QUECTEL:
            cmd = f'AT+QGNSSCW={interval}'
        self._at_command_response(cmd)
    
    def get_nmea_data(self,
                      stale_secs: int = 1,
                      wait_secs: int = 35,
                      rmc: bool = True,
                      gga: bool = True,
                      gsa: bool = True,
                      gsv: bool = False,
                      ) -> str:
        """Get a set of NMEA data detailing the modem's location.
        
        Args:
            stale_secs (int): Maximum cached fix age to use in seconds.
            wait_secs (int): Maximum duration to wait for a fix in seconds.
            rmc (bool): Include Recommended Minimum data.
            gga (bool): Include altitude and fix quality data.
            gsa (bool): Include Dilution of Precision data.
            gsv (bool): Include verbose GNSS satellite details.
        
        """
        cmd = 'AT%GPS'
        prefix = '%GPS:'
        if self._mfr == Manufacturer.QUECTEL:
            cmd = 'AT+QGNSS'
            prefix = '+QGNSS:'
        cmd += f'={stale_secs},{wait_secs}'
        if rmc:
            cmd += ',"RMC"'
        if gga:
            cmd += ',"GGA"'
        if gsa:
            cmd += ',"GSA"'
        if gsv:
            cmd += ',"GSV"'
        try:
            response = self._at_command_response(cmd, prefix, wait_secs + 5)
            return response
        except ModemAtError as exc:
            if exc.error_code != AtErrorCode.GNSS_TIMEOUT:
                raise
        return ''
    
    def get_location(self,
                     stale_secs: int = 1,
                     wait_secs: int = 35) -> 'ModemLocation|None':
        """Get the modem's location.
        
        Args:
            stale_secs (int): Maximum cached fix age to use in seconds.
            wait_secs (int): Maximum duration to wait for a fix in seconds.
        
        Returns:
            ModemLocation object if GNSS does not time out waiting for fix.
        
        """
        nmea_data = self.get_nmea_data(stale_secs, wait_secs)
        if nmea_data:
            return get_location_from_nmea_data(nmea_data)
        return None
    
    def get_satellite_info(self) -> 'SatelliteLocation|None':
        """Get the satellite's information including azimuth and elevation.
        
        Derives which satellite/GeoBeam is used from trace class 3 subclass 5.
        
        Returns:
            `SatelliteLocation` object (azimuth, elevation) if determinable.
        
        """
        geobeam = None
        modem_location = self.get_location()
        if (modem_location is not None and
            self.get_network_status() > NetworkStatus.RX_SEARCHING):
            # satellite has been found
            cmd = 'ATS90=3 S91=5 S92=1 S102?'
            prefix = ''
            if self._mfr == Manufacturer.QUECTEL:
                cmd = 'AT+QEVNT=3,5'
                prefix = '+QEVNT:'
            response = self._at_command_response(cmd, prefix)
            if self._mfr == Manufacturer.QUECTEL:
                # workaround documentation error
                response = response.replace('+QEVENT:', '').strip()
                response = response.split(',')[9]
            geobeam = GeoBeam(int(response))
        satellite_loc = get_satellite_location(modem_location, geobeam)
        return satellite_loc if satellite_loc.azimuth else None
    
    def get_event_mask(self) -> int:
        """Get the set of monitored events that trigger event notification."""
        if self._mfr != Manufacturer.ORBCOMM:
            raise ModemError('Operation not supported by this modem')
        cmd = 'ATS88?'
        return int(self._at_command_response(cmd))
    
    def set_event_mask(self, event_mask: int) -> None:
        """Set monitored events that trigger event notification."""
        if self._mfr != Manufacturer.ORBCOMM:
            raise ModemError('Operation not supported by this modem')
        max_bits = 12
        if not isinstance(event_mask, int) or event_mask > 2**max_bits-1:
            raise ValueError('Invalid event bitmask')
        cmd = f'ATS88={event_mask}'
        self._at_command_response(cmd)
    
    def get_events_asserted_mask(self) -> int:
        """Get the set of events that are active following a notification."""
        if self._mfr != Manufacturer.ORBCOMM:
            raise ModemError('Operation not supported by this modem')
        cmd = 'ATS89?'
        return int(self._at_command_response(cmd))
    
    def get_trace_event_monitor(self,
                                asserted_only: bool = False,
                                ) -> 'list[tuple[int, int]]':
        """Get the list of monitored Trace Events.
        
        Args:
            asserted_only (bool): If True returns only asserted monitored events
        
        Returns:
            A list of tuples (trace_class, trace_subclass)
        
        Raises:
            `ModemError` if unsupported by the modem type.
        
        """
        if self._mfr != Manufacturer.ORBCOMM:
            raise ModemError('Operation not supported by this modem')
        cmd = 'AT%EVMON'
        prefix = '%EVMON:'
        trace_events = []
        events = self._at_command_response(cmd, prefix).split(',')
        for event in events:
            trace_class = int(event.split('.')[0])
            trace_subclass = int(event.split('.')[1].replace('*', ''))
            if not asserted_only or event.endswith('*'):
                trace_events.append((trace_class, trace_subclass))
        return trace_events
    
    def set_trace_event_monitor(self, events: 'list[tuple[int, int]]') -> None:
        """Set the list of monitored trace events."""
        cmd = 'AT%EVMON='
        for event in events:
            if not cmd.endswith('='):
                cmd += ','
            cmd += f'{event[0].event[1]}'
        self._at_command_response(cmd)
    
    def get_trace_events_cached(self) -> 'list[tuple[int, int]]':
        """Get a list of trace events cached."""
        return self.get_trace_event_monitor(True)
    
    def get_trace_event_data(self,
                             event: 'tuple[int, int]',
                             decode: bool = False,
                             ) -> 'list[int]|dict[str, int]':
        """Get the trace event data.
        
        Args:
            event (tuple): The trace (class, subclass)
            decode (bool): Decodes raw data to dictionary (not implemented)
        
        """
        cmd = f'AT%EVNT={event[0]},{event[1]}'
        prefix = '%EVNT:'
        if self._mfr == Manufacturer.QUECTEL:
            cmd = cmd.replace('%EVNT', '+QEVNT')
            prefix = '+QEVENT:'   # documented as +QEVNT
        trace = self._at_command_response(cmd, prefix)
        if decode:
            raise NotImplementedError
        return [int(i) for i in trace.split(',')]
            
    def get_urc_ctl(self) -> int:
        """Get the event list that trigger Unsolicited Report Codes."""
        if self._mfr != Manufacturer.QUECTEL:
            raise ValueError('Modem does not support this feature')
        cmd = 'AT+QURCCTL?'
        prefix = '+QURCCTL:'
        return int(self._at_command_response(cmd, prefix), 16)
    
    def set_urc_ctl(self, qurc_mask: int) -> None:
        """Set the event list that trigger Unsolicited Report Codes."""
        if self._mfr != Manufacturer.QUECTEL:
            raise ValueError('Modem does not support this feature')
        cmd = f'AT+QURCCTL=0x{qurc_mask:04X}'
        self._at_command_response(cmd)
    
    def get_urc(self) -> 'UrcCode|None':
        """Get the pending Unsolicited Result Code if one is present."""
        if self._mfr != Manufacturer.QUECTEL:
            raise ValueError('Modem does not support this feature')
        eol = '\r\n' if self._modem.verbose else '\r'
        result = self._modem.read_line(eol)
        if result:
            result = result.replace('+QURC:', '').strip()
            try:
                return UrcCode(int(result))
            except ValueError:
                return UrcCode[result]
        return None
    
    def get_power_mode(self) -> PowerMode:
        """Get the modem's power mode configuration."""
        cmd = 'ATS50?'
        prefix = ''
        if self._mfr == Manufacturer.QUECTEL:
            cmd = 'AT+QPMD?'
            prefix = '+QPMD:'
        return PowerMode(int(self._at_command_response(cmd, prefix)))
    
    def set_power_mode(self, power_mode: PowerMode) -> None:
        """Set the modem's power mode configuration."""
        if not PowerMode.is_valid(power_mode):
            raise ValueError('Invalid Power Mode')
        cmd = f'ATS50={power_mode}'
        if self._mfr == Manufacturer.QUECTEL:
            cmd = f'AT+QPMD={power_mode}'
        self._at_command_response(cmd)
    
    def get_wakeup_period(self) -> WakeupPeriod:
        """Get the modem's wakeup period configuration."""
        cmd = 'ATS51?'
        prefix = ''
        if self._mfr == Manufacturer.QUECTEL:
            cmd = 'AT+QWKUPCFG?'
            prefix = '+QWKUPCFG:'
        if self._mfr == Manufacturer.QUECTEL:
            return WakeupPeriod(int(
                self._at_command_response(cmd, prefix).split(',')[0]))
        return WakeupPeriod(int(self._at_command_response(cmd, prefix)))
    
    def set_wakeup_period(self,
                          wakeup_period: WakeupPeriod,
                          wakeup_way: 'WakeupWay|None' = None,
                          ) -> None:
        """Set the modem's wakeup period configuration.
        
        The configuration does not update until confimed by the network.
        
        """
        if not WakeupPeriod.is_valid(wakeup_period):
            raise ValueError('Invalid wakeup period')
        cmd = f'ATS51={wakeup_period}'
        if self._mfr == Manufacturer.QUECTEL:
            if wakeup_way is None:
                query = self._at_command_response('AT+QWKUPCFG?', '+QWKUPCFG:')
                wakeup_way = WakeupWay(int(query.split(',')[1]))
            cmd = f'AT+QWKUPCFG={wakeup_period},{wakeup_way}'
        self._at_command_response(cmd)
    
    def get_wakeup_way(self) -> WakeupWay:
        """Get the modem wakeup method."""
        if self._mfr != Manufacturer.QUECTEL:
            raise ModemError('Operation not supported by this modem')
        cmd = 'AT+QWKUPCFG?'
        prefix = '+QWKUPCFG:'
        wakeup_way = self._at_command_response(cmd, prefix).split(',')[1]
        return WakeupWay(int(wakeup_way))
    
    def power_down(self) -> None:
        """Prepare the modem for power-down."""
        cmd = 'AT%OFF'
        if self._mfr == Manufacturer.QUECTEL:
            cmd = 'AT+QPOWD=2'
        self._at_command_response(cmd)
    
    def get_workmode(self) -> WorkMode:
        """Get the modem working mode."""
        if self._mfr != Manufacturer.QUECTEL:
            raise ModemError('Operation not supported by this modem')
        cmd = 'AT+QMOD?'
        prefix = '+QMOD:'
        return WorkMode(int(self._at_command_response(cmd, prefix)))
    
    def set_workmode(self, workmode: WorkMode) -> None:
        """Set the modem working mode."""
        if self._mfr != Manufacturer.QUECTEL:
            raise ModemError('Operation not supported by this modem')
        if not WorkMode.is_valid(workmode):
            raise ValueError('Invalid workmode')
        cmd = f'AT+QMOD={workmode}'
        self._at_command_response(cmd)
    
    def get_deepsleep_enable(self) -> bool:
        """Get the deepsleep configuration flag."""
        if self._mfr != Manufacturer.QUECTEL:
            raise ModemError('Operation not supported by this modem')
        cmd = 'AT+QSCLK?'
        prefix = '+QSCLK:'
        return bool(int(self._at_command_response(cmd, prefix)))
    
    def set_deepsleep_enable(self, enable: bool) -> None:
        """Set the deepsleep configuration flag."""
        if self._mfr != Manufacturer.QUECTEL:
            raise ModemError('Operation not supported by this modem')
        self._at_command_response(f'AT+QSCLK={int(enable)}')
    
    def get_register(self, s_register_number: int) -> 'int|None':
        """Get a modem register value."""
        cmd = f'ATS{s_register_number}?'
        return int(self._at_command_response(cmd))
    
    def set_register(self, s_register_number: int, value: int) -> None:
        """Set a modem register value."""
        cmd = f'ATS{s_register_number}={value}'
        self._at_command_response(cmd)
    
    def get_all_registers(self) -> dict:
        """Get a dictionary of modem register values."""
        raise NotImplementedError
