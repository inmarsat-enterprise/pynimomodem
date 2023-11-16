import logging
import os
from dataclasses import dataclass

from .atcommandbuffer import AtCommandBuffer
from .nimomessage import MoMessage, MtMessage, SatelliteMessageState
from .nmealocation import ModemLocation, get_location_from_nmea_data

LOG_VERBOSE = 'nimomodem' in str(os.getenv('LOG_VERBOSE'))
_log = logging.getLogger(__name__)


@dataclass
class SatelliteAcquisitionDetail:
    """"""
    vcid: int = 0
    rssi: float = 0.0
    ctrl_state: int = 0
    beam_search_state: int = 0


@dataclass
class MoSubmission:
    """"""
    success: bool = False
    name: str = ''


@dataclass
class ModemRegister:
    """"""


class NimoModem:
    """"""
    def __init__(self) -> None:
        self.at_command_buffer: AtCommandBuffer = None
        self._mobile_id: str = None
        self._cached_mobile_id: bool = False
        self._mfr_code: int = 0
        self._mfr_code_cached: bool = False
        self._modem_booted: bool = False
        self._queue = None
    
    def is_connected(self) -> bool:
        """"""
    
    def await_boot(self) -> bool:
        """"""
    
    def get_last_error_code(self) -> int:
        """"""
    
    def initialize(self,
                   echo: bool = True,
                   verbose: bool = True,
                   clear_queues: bool = False) -> bool:
        """"""
    
    def set_crc(self, enable: bool = False) -> bool:
        """"""
    
    def reset_factory_config(self) -> bool:
        """"""
    
    def save_config(self) -> bool:
        """"""
    
    def get_mobile_id(self) -> str:
        """"""
    
    def get_mfr_id(self) -> int:
        """"""
    
    def get_manufacturer(self) -> str:
        """"""
    
    def get_firmware_version(self) -> str:
        """"""
    
    def get_system_time(self) -> int:
        """"""
    
    def is_transmit_allowed(self) -> bool:
        """"""
    
    def is_blocked(self) -> bool:
        """"""
    
    def is_muted(self) -> bool:
        """"""
    
    def is_receiving_network_update(self) -> bool:
        """"""
    
    def get_satellite_status(self) -> int:
        """"""
    
    def get_rssi(self) -> float:
        """"""
    
    def get_signal_quality(self) -> int:
        """"""
    
    def get_acquisition_detail(self) -> SatelliteAcquisitionDetail:
        """"""
    
    def send_data(self,
                  data,
                  message_name: str = '',
                  priority: int = 4,
                  codec_sin: int = -1,
                  codec_min: int = -1) -> str:
        """"""
    
    def send_text(self, text: str) -> str:
        """"""
    
    def cancel_mo_message(self, message_name: str) -> int:
        """"""
    
    def get_mo_message_states(self) -> 'list[SatelliteMessageState]':
        """"""
    
    def get_mt_message_states(self) -> 'list[SatelliteMessageState]':
        """"""
    
    def _parse_message_states(self):
        """"""
    
    def _update_message_state(self):
        """"""
    
    def _update_mt_message(self):
        """"""
    
    def get_mt_message(self, message_name: str) -> MtMessage:
        """"""
    
    def del_mt_message(self, message_name: str) -> int:
        """"""
    
    def receive_data(self, message_name: str) -> bytes:
        """"""
    
    def get_gnss_mode(self) -> int:
        """"""
    
    def set_gnss_mode(self, gnss_mode: int) -> bool:
        """"""
    
    def get_gnss_refresh(self) -> int:
        """"""
    
    def set_gnss_refresh(self, refresh_interval: int) -> bool:
        """"""
    
    def _get_nmea_data(self):
        """"""
    
    def get_location(self,
                     stale_secs: int = 1,
                     wait_secs: int = 35) -> ModemLocation:
        """"""
    
    def get_event_mask(self) -> int:
        """"""
    
    def set_event_mask(self, event_mask: int) -> bool:
        """"""
    
    def get_events_asserted_mask(self) -> int:
        """"""
    
    def get_qurc_mask(self) -> int:
        """"""
    
    def set_qurc_mask(self, qurc_mask: int) -> bool:
        """"""
    
    def get_power_mode(self):
        """"""
    
    def set_power_mode(self, power_mode):
        """"""
    
    def get_wakeup_period(self) -> int:
        """"""
    
    def set_wakeup_period(self, wakeup_period: int) -> bool:
        """"""
    
    def set_powerdown(self) -> bool:
        """"""
    
    def get_qwakeupway(self):
        """"""
    
    def get_qworkmode(self):
        """"""
    
    def set_qworkmode(self, working_mode: int) -> bool:
        """"""
    
    def get_deepsleep_enable(self):
        """"""
    
    def set_deepsleep_enable(self, enable: bool) -> bool:
        """"""
    
    def get_register(self, s_register_number: int) -> int:
        """"""
    
    def set_register(self, s_register_number: int, value: int) -> bool:
        """"""
    
    def get_all_registers(self):
        """"""
