import logging

from .nimoutils import vlog

VLOG_TAG = 'nmealocation'

_log = logging.getLogger(__name__)


class ModemLocation:
    """"""
    def __init__(self) -> None:
        raise NotImplementedError


def validate_nmea(nmea: str) -> bool:
    """Validates a given NMEA-0183 sentence with CRC."""
    raise NotImplementedError


def parse_nmea_to_location(location: ModemLocation, nmea: str) -> None:
    """Parses a NMEA-0183 sentence to update a ModemLocation."""
    raise NotImplementedError


def get_location_from_nmea_data(nmea_sentences: str) -> ModemLocation:
    """Derives a ModemLocation from a set of NMEA-0183 sentences."""
    raise NotImplementedError
