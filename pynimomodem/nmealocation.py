"""Utilities for validating and parsing NMEA-0183 data into a `Location` object.
"""
import logging
import json
from copy import deepcopy
from dataclasses import dataclass

from .nimoconstants import NimoIntEnum
from .nimoutils import vlog, iso_to_ts, ts_to_iso

VLOG_TAG = 'nmealocation'

_log = logging.getLogger(__name__)


class GnssFixType(NimoIntEnum):
    NONE = 1
    D2 = 2
    D3 = 3


class GnssFixQuality(NimoIntEnum):
    INVALID = 0
    GPS_SPS = 1
    DGPS = 2
    PPS = 3
    RTK = 4
    FLOAT_RTK = 5
    EST_DEAD_RECKONING = 6
    MANUAL = 7
    SIMULATION = 8


@dataclass
class GnssSatelliteInfo(object):
    """Information specific to a GNSS satellite.
    
    Attributes:
        prn: The PRN code (Pseudo-Random Number sequence)
        elevation: The satellite elevation
        azimuth: The satellite azimuth
        snr: The satellite Signal-to-Noise Ratio
    """
    prn: int
    elevation: int
    azimuth: int
    snr: int


class Location:
    """A set of location-based information derived from the modem's NMEA data.
    
    Uses 90.0/180.0 if latitude/longitude are unknown

    Attributes:
        latitude (float): decimal degrees
        longitude (float): decimal degrees
        altitude (float): in metres
        speed (float): in knots
        heading (float): in degrees
        timestamp (int): in seconds since 1970-01-01T00:00:00Z
        satellites (int): in view at time of fix
        fix_type (GnssFixType): 1=None, 2=2D or 3=3D
        fix_quality (GnssFixQuality): Enumerated lookup value
        pdop (float): Probability Dilution of Precision
        hdop (float): Horizontal Dilution of Precision
        vdop (float): Vertical Dilution of Precision
        time_iso (str): ISO 8601 formatted timestamp

    """
    def __init__(self, **kwargs):
        """Initializes a Location with default latitude/longitude 90/180."""
        self.latitude = float(kwargs.get('latitude', 90.0))
        self.longitude = float(kwargs.get('longitude', 180.0))
        self.altitude = float(kwargs.get('altitude', 0.0))   # metres
        self.speed = float(kwargs.get('speed', 0.0))  # knots
        self.heading = float(kwargs.get('heading', 0.0))   # degrees
        self.timestamp = int(kwargs.get('timestamp', 0))   # seconds (unix)
        self.satellites = int(kwargs.get('satellites', 0))
        self.fix_type = GnssFixType(int(kwargs.get('fix_type', 1)))
        self.fix_quality = GnssFixQuality(int(kwargs.get('fix_quality', 0)))
        self.pdop = float(kwargs.get('pdop', 99))
        self.hdop = float(kwargs.get('hdop', 99))
        self.vdop = float(kwargs.get('vdop', 99))
        # self.satellites_info: 'list[GnssSatelliteInfo]' = kwargs.get(
        #     'satellites_info', []
        # )

    @property
    def time_iso(self) -> str:
        return f'{ts_to_iso(self.timestamp)}'

    # def _update_satellites_info(self,
    #                             satellites_info: 'list[GnssSatelliteInfo]'):
    #     """Populates satellite information based on NMEA GSV data."""
    #     for satellite_info in satellites_info:
    #         if isinstance(satellite_info, GnssSatelliteInfo):
    #             new = True
    #             for i, info in enumerate(self.satellites_info):
    #                 if info.prn == satellite_info.prn:
    #                     new = False
    #                     self.satellites_info[i] = satellite_info
    #                     break
    #             if new:
    #                 self.satellites_info.append(satellite_info)

    def __repr__(self) -> str:
        obj = deepcopy(self.__dict__)
        for k, v in obj.items():
            if k in ['latitude', 'longitude']:
                obj[k] = round(v, 5)
            elif isinstance(v, float):
                obj[k] = round(v, 1)
        return json.dumps(obj, skipkeys=True)


def validate_nmea(nmea_sentence: str) -> bool:
    """Validates a given NMEA-0183 sentence with CRC.
    
    Args:
        nmea_sentence (str): NMEA-0183 sentence ending in checksum.
    
    """
    if '*' not in nmea_sentence:
        return False
    data, cs_hex = nmea_sentence.split('*')
    candidate = int(cs_hex, 16)
    crc = 0   # initial
    for i in range(1, len(data)):   # ignore initial $
        crc ^= ord(data[i])
    return candidate == crc


def parse_nmea_to_location(location: Location, nmea_sentence: str) -> None:
    """Parses a NMEA-0183 sentence to update a ModemLocation."""
    if vlog(VLOG_TAG):
        _log.debug('Parsing NMEA: %s', nmea_sentence)
    if not validate_nmea(nmea_sentence):
        raise ValueError('Invalid NMEA-0183 sentence')
    data = nmea_sentence.split('*')[0]
    nmea_type = ''
    cache = {}
    for i, field_data in enumerate(data.split(',')):
        if i == 0:
            nmea_type = field_data[-3:]
            if nmea_type == 'GSV':
                _log.warn('No processing required for GSV sentence')
                return
            if nmea_type == 'GSA' and location.vdop != 99:
                if vlog(VLOG_TAG):
                    _log.debug('Skipping redundant GSA data')
                return
            if vlog(VLOG_TAG):
                _log.debug('Processing NMEA type: %s', nmea_type)
        elif i == 1:
            if nmea_type == 'RMC':
                cache['fix_hour'] = field_data[0:2]
                cache['fix_min'] = field_data[2:4]
                cache['fix_sec'] = field_data[4:6]
                if vlog(VLOG_TAG):
                    _log.debug('Fix time %s:%s:%s', cache['fix_hour'],
                               cache['fix_min'], cache['fix_sec'])
        elif i == 2:
            if nmea_type == 'RMC':
                if (field_data == 'V'):
                    _log.warn('Fix Void')
            elif nmea_type == 'GSA':
                location.fix_type = GnssFixType(int(field_data))
                if vlog(VLOG_TAG):
                    _log.debug('Fix type: %s', location.fix_type.name)
        elif i == 3:
            if nmea_type == 'RMC':
                location.latitude = (float(field_data[0:2]) +
                                     float(field_data[2]) / 60.0)
        elif i == 4:
            if nmea_type == 'RMC':
                if field_data == 'S':
                    location.latitude *= -1
                if vlog(VLOG_TAG):
                    _log.debug('Latitude: %.5f', location.latitude)
        elif i == 5:
            if nmea_type == 'RMC':
                location.longitude = (float(field_data[0:3]) +
                                      float(field_data[3]) / 60.0)
        elif i == 6:
            if nmea_type == 'RMC':
                if field_data == 'W':
                    location.longitude *= -1
                if vlog(VLOG_TAG):
                    _log.debug('Longitude: %.5f', location.longitude)
            elif nmea_type == 'GGA':
                location.fix_quality = GnssFixQuality(int(field_data))
                if vlog(VLOG_TAG):
                    _log.debug('Fix quality: %s', location.fix_quality.name)
        elif i == 7:
            if nmea_type == 'RMC':
                location.speed = float(field_data)
                if vlog(VLOG_TAG):
                    _log.debug('Speed: %.1f', location.speed)
            elif nmea_type == 'GGA':
                location.satellites = int(field_data)
                if vlog(VLOG_TAG):
                    _log.debug('GNSS satellites used: %d', location.satellites)
        elif i == 8:
            if nmea_type == 'RMC':
                location.heading = float(field_data)
                if vlog(VLOG_TAG):
                    _log.debug('Heading: %.1f', location.heading)
            elif nmea_type == 'GGA':
                location.hdop = round(float(field_data), 1)
                if vlog(VLOG_TAG):
                    _log.debug('HDOP: %.1f', location.heading)
        elif i == 9:
            if nmea_type == 'RMC':
                fix_day = field_data[0:2]
                fix_month = field_data[2:4]
                fix_yy = int(field_data[4:])
                fix_yy += 1900 if fix_yy >= 73 else 2000
                if vlog(VLOG_TAG):
                    _log.debug('Fix date %d-%s-%s', fix_yy, fix_month, fix_day)
                iso_time = (f'{fix_yy}-{fix_month}-{fix_day}T'
                            f'{cache["fix_hour"]}:{cache["fix_min"]}'
                            f':{cache["fix_sec"]}Z')
                unix_timestamp = iso_to_ts(iso_time)
                if vlog(VLOG_TAG):
                    _log.debug('Fix time ISO 8601: %s | Unix: %d',
                               iso_time, unix_timestamp)
                location.timestamp = unix_timestamp
            elif nmea_type == 'GGA':
                location.altitude = float(field_data)
                if vlog(VLOG_TAG):
                    _log.debug('Altitude: %.1f', location.altitude)
        elif i == 10:
            # RMC magnetic variation - ignore
            if nmea_type == 'GGA' and field_data != 'M':
                _log.warning('Unexpected altitude units: %s', field_data)
        # elif i == 11:   # RMC magnetic variation direction, GGA height of geoid - ignore
        # elif i == 12:   # GGA units height of geoid - ignore
        # elif i == 13:   # GGA seconds since last DGPS update - ignore
        # elif i == 14:   # GGA DGPS station ID - ignore
        elif i == 15:   # GSA PDOP - ignore (unused)
            if nmea_type == 'GSA':
                location.pdop = round(float(field_data), 1)
                if vlog(VLOG_TAG):
                    _log.debug('PDOP: %d', location.pdop)
        # elif i == 16:   # GSA HDOP - ignore (use GGA)
        elif i == 17:
            if nmea_type == 'GSA':
                location.vdop = round(float(field_data), 1)
                if vlog(VLOG_TAG):
                    _log.debug('VDOP: %d', location.vdop)


def get_location_from_nmea_data(nmea_sentences: 'str|list[str]') -> Location:
    """Derives a ModemLocation from a set of NMEA-0183 sentences.
    
    Args:
        nmea_sentences (str): A set of NMEA-0183 sentences separated by `\n` or
            a list of sentences.
    
    Returns:
        `Location` object.
    
    """
    location = Location()
    if isinstance(nmea_sentences, list):
            if not all(isinstance(x, str) for x in nmea_sentences):
                raise ValueError('Invalid NMEA sentence list')
    elif isinstance(nmea_sentences, str):
        nmea_sentences = nmea_sentences.split('\n')
    for nmea_sentence in nmea_sentences:
        parse_nmea_to_location(location, nmea_sentence)
    return location


# def _parse_gsv_to_location(location: Location, gsv_sentence: str) -> None:
#     """Returns a Location object based on an NMEA sentences data set.
#
#     Placeholder - overcomplicates Location object
#
#     Args:
#         location: The Location object to update
#         gsv_sentence: The Satellites in View sentence to parse
#
#     """
#     update_satellites = getattr(location, '_update_satellites_info', None)
#     if not callable(update_satellites):
#         raise ValueError('Location object does not support GSV parsing')
#     gsv = gsv_sentence.split(',')       # $GPGSV,2,1,08,01,40,083,46,02,17,308,41,12,07,344,39,14,22,228,45*75
#     '''
#     gsv_sentences = gsv[1]           # Number of sentences for full data
#     gsv_sentence = gsv[2]            # Sentence number (up to 4 satellites per sentence)
#     '''
#     gsv_satellites = gsv[3]          # Number of satellites in view
#     # following supports up to 4 satellites per sentence
#     satellites_info = []
#     if (len(gsv) - 4) % 4 > 0:
#         # TODO: warn/log this case of extra GSV data in sentence
#         pass
#     num_satellites_in_sentence = int((len(gsv)-4)/4)
#     for i in range(1, num_satellites_in_sentence+1):
#         prn = int(gsv[i*4]) if gsv[i*4] != '' else 0             # satellite PRN number
#         elevation = int(gsv[i*4+1]) if gsv[i*4+1] != '' else 0   # Elevation in degrees
#         azimuth = int(gsv[i*4+2]) if gsv[i*4+2] != '' else 0     # Azimuth in degrees
#         snr = int(gsv[i*4+3]) if gsv[i*4+3] != '' else 0         # Signal to Noise Ratio
#         satellites_info.append(GnssSatelliteInfo(prn,
#                                                     elevation,
#                                                     azimuth,
#                                                     snr))
#     location._update_satellites_info(satellites_info)
#     satellites = int(gsv_satellites) if gsv_satellites != '' else 0
#     if location.satellites < satellites:
#         location.satellites = satellites
#     else:
#         # TODO: log this case; should be limited to GPS simulation in Modem Simulator (3 satellites)
#         pass
