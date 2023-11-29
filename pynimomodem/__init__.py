"""Library to interface with a Viasat-approved NIMO modem for satellite IoT.

Depends on either Python/PySerial or Micropython/machine library.

"""

from .constants import (
    EventNotification,
    GnssMode,
    MessagePriority,
    MessageState,
    PowerMode,
    SignalQuality,
    UrcCode,
    UrcControl,
    WakeupPeriod,
    WakeupWay,
    WorkMode,
)
from .modem import (
    Manufacturer,
    ModemLocation,
    MoMessage,
    MtMessage,
    NimoModem,
    NimoModemError,
    SatelliteAcquisitionDetail,
    SatelliteLocation,
)

__all__ = [
    'GnssMode',
    'Manufacturer',
    'MessagePriority',
    'MessageState',
    'ModemLocation',
    'MoMessage',
    'MtMessage',
    'NimoModem',
    'NimoModemError',
    'PowerMode',
    'SatelliteAcquisitionDetail',
    'SatelliteLocation',
    'SignalQuality',
    'WakeupPeriod',
    'WakeupWay',
    'WorkMode',
    'UrcCode',
    'UrcControl',
    'EventNotification',
]