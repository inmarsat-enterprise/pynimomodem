import logging
import os
import time
import base64
from dataclasses import dataclass
from enum import IntEnum

from .atcommandbuffer import DEFAULT_AT_TIMEOUT, AtCommandBuffer, Serial
from .nimoconstants import (
    MSG_MO_MAX_SIZE,
    AtErrorCode,
    BeamSearchState,
    SatelliteControlState,
    SignalLevelRegional,
    SignalQuality,
)
from .nimomessage import MoMessage, MtMessage, SatelliteMessageState
from .nimoutils import iso_to_ts
from .nmealocation import ModemLocation, get_location_from_nmea_data

LOG_VERBOSE = 'nimomodem' in str(os.getenv('LOG_VERBOSE'))
_log = logging.getLogger(__name__)


class Manufacturer(IntEnum):
    NONE = 0
    ORBCOMM = 1
    QUECTEL = 2


@dataclass
class SatelliteAcquisitionDetail:
    """"""
    vcid: int = 0
    rssi: float = 0.0
    ctrl_state: SatelliteControlState = SatelliteControlState.STOPPED
    beam_search_state: BeamSearchState = BeamSearchState.IDLE


@dataclass
class MoSubmission:
    """"""
    success: bool = False
    name: str = ''


@dataclass
class ModemRegister:
    """"""


class NimoModemError(Exception):
    """"""


class NimoModem:
    """A class for NIMO satellite IoT modem interaction."""
    # __slots__ = ('_modem', '_mobile_id',
    #              '_mfr_code', '_modem_booted', '_queue',
    #              )
    
    def __init__(self, serial: Serial) -> None:
        self._modem: AtCommandBuffer = AtCommandBuffer(serial)
        self._modem_booted: bool = False
        self._mobile_id: str = ''
        self._manufacturer: str = ''
        self._queue = None
    
    @property
    def crc_enabled(self) -> bool:
        return self._modem.crc
    
    @property
    def modem_booted(self) -> bool:
        return self._modem_booted
    
    def _mfr_id(self) -> Manufacturer:
        if not self._manufacturer:
            self.get_manufacturer()
        if self._manufacturer == 'ORBCOMM':
            return Manufacturer.ORBCOMM
        if self._manufacturer == 'QUECTEL':
            return Manufacturer.QUECTEL
        return Manufacturer.NONE
    
    def _mo_msg_name_len_max(self) -> int:
        mfr = self._mfr_id()
        maxlen = 8
        if mfr == Manufacturer.QUECTEL:
            maxlen = 12
        return maxlen
    
    def _at_command_response(self,
                             command: str,
                             prefix: str = '',
                             timeout: int = DEFAULT_AT_TIMEOUT) -> str:
        """Send a command and return the response."""
        self._modem.send_at_command(command)
        err = self._modem.read_at_response(prefix, timeout)
        if err == AtErrorCode.OK:
            return self._modem.get_response()
        raise NimoModemError(err)
    
    def is_connected(self) -> bool:
        """Indicates if the modem is responding to a basic AT query."""
        try:
            self._at_command_response('AT')
            self._modem_booted = True
            return True
        except NimoModemError:
            self._modem_booted = False
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
    
    def get_last_error_code(self) -> int:
        """Get the last error code from the modem."""
        try:
            return int(self._at_command_response('ATS80?'))
        except NimoModemError as exc:
            _log.error(exc)
    
    def initialize(self,
                   echo: bool = True,
                   verbose: bool = True,
                   ) -> bool:
        """Initialize the modem AT configuration for Echo and Verbose."""
        at_command = (f'ATZ;E{int(echo)};V{int(verbose)}')
        try:
            self._at_command_response(at_command)
            return True
        except NimoModemError as exc:
            if exc.args[0] == AtErrorCode.CRC_CONFIG_MISMATCH:
                try:
                    _log.info('Retry initialization with CRC enabled')
                    self._at_command_response(at_command)
                    return True
                except NimoModemError:
                    pass
            return False
    
    def set_crc(self, enable: bool = False) -> bool:
        """Enable or disable CRC error checking on the modem serial port."""
        try:
            self._at_command_response(f'AT%CRC={int(enable)}')
            return True
        except NimoModemError as exc:
            if exc.args[0] == AtErrorCode.CRC_CONFIG_MISMATCH:
                if ((self._modem.crc and enable) or
                    (not self._modem.crc and not enable)):
                    return True
            return False
    
    def reset_factory_config(self) -> bool:
        """Reset the modem's factory default configuration."""
        try:
            self._at_command_response('AT&F')
            return True
        except NimoModemError:
            return False
    
    def save_config(self) -> bool:
        """Store the current configuration to modem non-volatile memory."""
        try:
            self._at_command_response('AT&W')
            return True
        except NimoModemError:
            return False
    
    def get_mobile_id(self) -> str:
        """Get the modem's globally unique identifier."""
        if not self._mobile_id:
            try:
                self._mobile_id = self._at_command_response('AT+GSN', '+GSN:')
            except NimoModemError:
                self._mobile_id = ''
        return self._mobile_id
    
    def get_manufacturer(self) -> str:
        """Get the manufacturer name."""
        if not self._manufacturer:
            try:
                manufacturer = self._at_command_response('AT+GMI', '+GMI:')
                if any(m in manufacturer.lower() for m in ['orbcomm', 'skywave']):
                    self._manufacturer = 'ORBCOMM'
                elif 'quectel' in manufacturer.lower():
                    self._manufacturer = 'QUECTEL'
            except NimoModemError:
                self._manufacturer = ''
        return self._manufacturer
    
    def get_firmware_version(self) -> str:
        """Get the modem's firmware version."""
        # TODO: Firmware structure with hardware, firmware, software?
        try:
            return self._at_command_response('AT+GMR', '+GMR:')
        except NimoModemError:
            return ''
    
    def get_system_time(self) -> int:
        """Get the system/GNSS time from the modem."""
        try:
            nimo_time = self._at_command_response('AT%UTC', '%UTC:')
            iso_time = nimo_time.replace(' ', 'T') + 'Z'
            return iso_to_ts(iso_time)
        except NimoModemError:
            return 0
    
    def is_transmit_allowed(self) -> bool:
        """Indicates if the modem is able to transmit data."""
        return self.get_satellite_status() == 5
    
    def is_blocked(self) -> bool:
        """Indicates if line-of-sight to the satellite is blocked."""
        return self.get_satellite_status() == 8
    
    def is_muted(self) -> bool:
        """Indicates if the modem has been muted (disallowed to transmit data).
        """
        return self.get_satellite_status() == 7
    
    def is_updating_network(self) -> bool:
        """Indicates if the modem is updating network information.
        
        The modem should not be powered down during a network update.
        
        """
        return self.get_satellite_status() == 4
    
    def get_satellite_status(self) -> int:
        """Get the current satellite acquisition status."""
        mfr = self._mfr_id()
        cmd = 'ATS54?'
        prefix = ''
        if mfr == Manufacturer.QUECTEL:
            cmd = 'AT+QREG?'
            prefix = '+QREG:'
        try:
            return int(self._at_command_response(cmd, prefix))
        except NimoModemError:
            return 0
    
    def get_rssi(self) -> float:
        """Get the current Received Signal Strength Indicator.
        
        Also referred to as SNR or C/N0 (dB-Hz)
        
        """
        try:
            cmd = 'ATS90=3 S91=1 S92=1 S116?'
            return int(self._at_command_response(cmd)) / 100
        except NimoModemError:
            return 0
    
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
    
    def get_acquisition_detail(self) -> 'SatelliteAcquisitionDetail|None':
        """Get the detailed satellite acquisition status.
        
        Includes `acquisition_state`, `beamsearch_state`, `vcid` and `snr`
        indicators.
        
        """
        cmd = 'ATS90=3 S91=1 S92=1 S122? S123? S116? S101?'
        try:
            result_str = self._at_command_response(cmd)
            results = [int(x) for x in result_str.split('\n')]
            ctrl_state = SatelliteControlState(results[0])
            beam_state = BeamSearchState(results[1])
            rssi = float(results[2]) / 100
            vcid = results[3]
            return SatelliteAcquisitionDetail(ctrl_state=ctrl_state,
                                              beam_search_state=beam_state,
                                              rssi=rssi,
                                              vcid=vcid)
        except NimoModemError:
            return None
    
    def send_data(self,
                  data: bytes,
                  message_name: str = '',
                  priority: int = 4,
                  codec_sin: int = -1,
                  codec_min: int = -1) -> str:
        """Submits data to send as a mobile-originated message."""
        data_size = len(data)
        if codec_sin > -1:
            data_size += 1
        if codec_min > -1:
            data_size += 1
        if not 2 <= data_size <= MSG_MO_MAX_SIZE:
            raise ValueError('Invalid mobile-originated message size')
        if message_name and len(message_name) > 8:
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
        if len(message_name) == 0:
            message_name = f'{int(time.time())}'
            maxlen = self._mo_msg_name_len_max()
            if len(message_name) > maxlen:
                message_name = message_name[-maxlen:]
        b64_str = base64.b64encode(data[2:].decode('utf-8'))
        mfr = self._mfr_id()
        cmd = 'AT%MGRT='
        codec_sep = '.'
        if mfr == Manufacturer.QUECTEL:
            cmd = 'AT+QSMGT='
            codec_sep = ','
        cmd = (f'{cmd}"{message_name}",{priority},{codec_sin}{codec_sep}'
               f'{codec_min},3,{b64_str}')
        try:
            self._at_command_response(cmd)
            return message_name
        except NimoModemError:
            return ''
    
    def send_text(self,
                  text: str,
                  message_name: str = '',
                  codec_sin: int = 128,
                  codec_min: int = 0,
                  ) -> str:
        """Submits a text string to send as data."""
        data = codec_sin.to_bytes(1, 'big') + codec_min.to_bytes(1, 'big')
        data += text.encode()
        return self.send_data(data, message_name)
    
    def cancel_mo_message(self, message_name: str) -> int:
        """Attempts to cancel a previously submitted mobile-originated message.
        """
    
    def get_mo_message_states(self) -> 'list[SatelliteMessageState]':
        """Get a list of mobile-originated message states in the modem Tx queue.
        """
    
    def get_mt_message_states(self) -> 'list[SatelliteMessageState]':
        """Get a list of mobile-terminated message states in the modem Tx queue.
        """
    
    def _parse_message_states(self):
        """Parses textual metadata to build a SatelliteMessageState."""
    
    def _update_message_state(self):
        """Parse textual metadata to update a message's state."""
    
    def _update_mt_message(self):
        """Parse textual metadata to build a MobileTerminatedMessage."""
    
    def get_mt_message(self, message_name: str) -> MtMessage:
        """Get a mobile-terminated message from the modem's Rx queue by name."""
    
    def del_mt_message(self, message_name: str) -> int:
        """Remove a mobile-terminated message from the modem's Rx queue."""
    
    def receive_data(self, message_name: str) -> bytes:
        """Get the raw data from a mobile-terminated message."""
    
    def get_gnss_mode(self) -> int:
        """Get the modem's GNSS receiver mode."""
    
    def set_gnss_mode(self, gnss_mode: int) -> bool:
        """Get the modem's GNSS receiver mode."""
    
    def get_gnss_refresh(self) -> int:
        """Get the modem's GNSS refresh interval in seconds."""
    
    def set_gnss_refresh(self, refresh_interval: int) -> bool:
        """Set the modem's GNSS refresh interval in seconds."""
    
    def _get_nmea_data(self):
        """Get a set of NMEA data to derive a location."""
    
    def get_location(self,
                     stale_secs: int = 1,
                     wait_secs: int = 35) -> ModemLocation:
        """Get the modem's location."""
    
    def get_event_mask(self) -> int:
        """Get the set of monitored events that trigger event notification."""
    
    def set_event_mask(self, event_mask: int) -> bool:
        """Set monitored events that trigger event notification."""
    
    def get_events_asserted_mask(self) -> int:
        """Get the set of events that are active following a notification."""
    
    def get_qurc_mask(self) -> int:
        """Get the event list that trigger Unsolicited Report Codes."""
    
    def set_qurc_mask(self, qurc_mask: int) -> bool:
        """Set the event list that trigger Unsolicited Report Codes."""
    
    def get_power_mode(self) -> int:
        """Get the modem's power mode configuration."""
    
    def set_power_mode(self, power_mode: int) -> bool:
        """Set the modem's power mode configuration."""
    
    def get_wakeup_period(self) -> int:
        """Get the modem's wakeup period configuration."""
    
    def set_wakeup_period(self, wakeup_period: int) -> bool:
        """Set the modem's wakeup period configuration.
        
        The configuration does not update until confimed by the network.
        
        """
    
    def set_powerdown(self) -> bool:
        """Prepare the modem for power-down."""
    
    def get_qwakeupway(self):
        """Get the modem wakeup method."""
    
    def get_qworkmode(self):
        """Get the modem working mode."""
    
    def set_qworkmode(self, working_mode: int) -> bool:
        """Set the modem working mode."""
    
    def get_deepsleep_enable(self):
        """Get the deepsleep configuration flag."""
    
    def set_deepsleep_enable(self, enable: bool) -> bool:
        """Set the deepsleep configuration flag."""
    
    def get_register(self, s_register_number: int) -> int:
        """Get a modem register value."""
    
    def set_register(self, s_register_number: int, value: int) -> bool:
        """Set a modem register value."""
    
    def get_all_registers(self) -> dict:
        """Get a dictionary of modem register values."""
