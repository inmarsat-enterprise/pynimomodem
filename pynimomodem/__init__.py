"""Library to interface with a Viasat-approved NIMO modem for satellite IoT.

This library abstracts various low-level AT command operations useful for
interacting with a NIMO modem to send and receive data, check network status
and get location-based information.

Most `get` methods will raise a `ModemAtError` if a valid response is not
received to a command/query.

`ModemTimeout` will be raised if no response is received to a command within
the default or specified timeout.

AT command errors will raise `ModemAtError` with a property `error_code` to
provide further details with the `AtErrorCode`.

"""

from .constants import (
    AtErrorCode,
    BeamState,
    ControlState,
    EventNotification,
    GnssMode,
    MessagePriority,
    MessageState,
    NetworkStatus,
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
    ModemError,
    SatelliteAcquisitionDetail,
    SatelliteLocation,
)

__all__ = [
    'AtErrorCode',
    'BeamState',
    'ControlState',
    'GnssMode',
    'Manufacturer',
    'MessagePriority',
    'MessageState',
    'ModemLocation',
    'MoMessage',
    'MtMessage',
    'NetworkStatus',
    'NimoModem',
    'ModemError',
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