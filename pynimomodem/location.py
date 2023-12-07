"""Classes and methods for location, elevation and azimuth for NIMO modems.

This module:

* Parses NMEA-0183 data into a `ModemLocation` object.
* Calculates azimuth and elevation to a geostationary `SatelliteLocation`.

Thanks for Azimuth/Elevation derived from code at:
https://github.com/sq3tle/altazrange/tree/master

"""
import json
import logging
import math
from copy import deepcopy
from dataclasses import dataclass

from .constants import (
    GEOSTATIONARY_DISTANCE_M,
    GeoBeam,
    GeoSatellite,
    NimoIntEnum,
)
from .nimoutils import iso_to_ts, ts_to_iso, vlog

VLOG_TAG = 'nmealocation'
TRACE_TAG = VLOG_TAG + 'trace'

_log = logging.getLogger(__name__)


class GnssFixType(NimoIntEnum):
    """Enumerated fix type from NMEA-0183 standard."""
    NONE = 1
    D2 = 2
    D3 = 3


class GnssFixQuality(NimoIntEnum):
    """Enumerated fix quality from NMEA-0183 standard."""
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


class ModemLocation:
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


@dataclass
class SatelliteLocation:
    """Represents a geostationary satellite location relative to a modem."""
    name: str = ''
    latitude: float = 0.0
    longitude: float = 180.0
    altitude: float = GEOSTATIONARY_DISTANCE_M
    azimuth: float = 0.0
    elevation: float = 0.0
    geobeam: 'GeoBeam|None' = None


@dataclass
class _PointLocation:
    """Location used for spherical coordinates (for azimuth/elevation)."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    radius: float = 0.0
    nx: float = 0.0
    ny: float = 0.0
    nz: float = 0.0


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


def parse_nmea_to_location(location: ModemLocation, nmea_sentence: str) -> None:
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
                if vlog(TRACE_TAG):
                    _log.debug('Skipping redundant GSA data')
                return
            if vlog(TRACE_TAG):
                _log.debug('Processing NMEA type: %s', nmea_type)
        elif i == 1:
            if nmea_type == 'RMC':
                cache['fix_hour'] = field_data[0:2]
                cache['fix_min'] = field_data[2:4]
                cache['fix_sec'] = field_data[4:6]
                if vlog(TRACE_TAG):
                    _log.debug('Fix time %s:%s:%s', cache['fix_hour'],
                               cache['fix_min'], cache['fix_sec'])
        elif i == 2:
            if nmea_type == 'RMC':
                if (field_data == 'V'):
                    _log.warn('Fix Void')
            elif nmea_type == 'GSA':
                location.fix_type = GnssFixType(int(field_data))
                if vlog(TRACE_TAG):
                    _log.debug('Fix type: %s', location.fix_type.name)
        elif i == 3:
            if nmea_type == 'RMC':
                location.latitude = (float(field_data[0:2]) +
                                     float(field_data[2]) / 60.0)
        elif i == 4:
            if nmea_type == 'RMC':
                if field_data == 'S':
                    location.latitude *= -1
                if vlog(TRACE_TAG):
                    _log.debug('Latitude: %.5f', location.latitude)
        elif i == 5:
            if nmea_type == 'RMC':
                location.longitude = (float(field_data[0:3]) +
                                      float(field_data[3]) / 60.0)
        elif i == 6:
            if nmea_type == 'RMC':
                if field_data == 'W':
                    location.longitude *= -1
                if vlog(TRACE_TAG):
                    _log.debug('Longitude: %.5f', location.longitude)
            elif nmea_type == 'GGA':
                location.fix_quality = GnssFixQuality(int(field_data))
                if vlog(TRACE_TAG):
                    _log.debug('Fix quality: %s', location.fix_quality.name)
        elif i == 7:
            if nmea_type == 'RMC':
                location.speed = float(field_data)
                if vlog(TRACE_TAG):
                    _log.debug('Speed: %.1f', location.speed)
            elif nmea_type == 'GGA':
                location.satellites = int(field_data)
                if vlog(TRACE_TAG):
                    _log.debug('GNSS satellites used: %d', location.satellites)
        elif i == 8:
            if nmea_type == 'RMC':
                location.heading = float(field_data)
                if vlog(TRACE_TAG):
                    _log.debug('Heading: %.1f', location.heading)
            elif nmea_type == 'GGA':
                location.hdop = round(float(field_data), 1)
                if vlog(TRACE_TAG):
                    _log.debug('HDOP: %.1f', location.heading)
        elif i == 9:
            if nmea_type == 'RMC':
                fix_day = field_data[0:2]
                fix_month = field_data[2:4]
                fix_yy = int(field_data[4:])
                fix_yy += 1900 if fix_yy >= 73 else 2000
                if vlog(TRACE_TAG):
                    _log.debug('Fix date %d-%s-%s', fix_yy, fix_month, fix_day)
                iso_time = (f'{fix_yy}-{fix_month}-{fix_day}T'
                            f'{cache["fix_hour"]}:{cache["fix_min"]}'
                            f':{cache["fix_sec"]}Z')
                unix_timestamp = iso_to_ts(iso_time)
                if vlog(TRACE_TAG):
                    _log.debug('Fix time ISO 8601: %s | Unix: %d',
                               iso_time, unix_timestamp)
                location.timestamp = unix_timestamp
            elif nmea_type == 'GGA':
                location.altitude = float(field_data)
                if vlog(TRACE_TAG):
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
                if vlog(TRACE_TAG):
                    _log.debug('PDOP: %d', location.pdop)
        # elif i == 16:   # GSA HDOP - ignore (use GGA)
        elif i == 17:
            if nmea_type == 'GSA':
                location.vdop = round(float(field_data), 1)
                if vlog(TRACE_TAG):
                    _log.debug('VDOP: %d', location.vdop)


def get_location_from_nmea_data(nmea_data: 'str|list[str]') -> ModemLocation:
    """Derives a ModemLocation from a set of NMEA-0183 sentences.
    
    Args:
        nmea_data (str): A set of NMEA-0183 sentences separated by `\n` or
            a `list` of NMEA sentences.
    
    Returns:
        `Location` object.
    
    """
    location = ModemLocation()
    if isinstance(nmea_data, list):
            if not all(isinstance(x, str) for x in nmea_data):
                raise ValueError('Invalid NMEA sentence list')
    elif isinstance(nmea_data, str):
        nmea_data = nmea_data.split('\n')
    for nmea_sentence in nmea_data:
        parse_nmea_to_location(location, nmea_sentence)
    if vlog(VLOG_TAG):
        _log.debug('Location: %s', repr(location))
    return location


def get_closest_satellite(latitude: float, longitude: float) -> GeoSatellite:
    """Get the closest geostationary satellite to a given location."""
    satellites = list(map(lambda x: x.value,GeoSatellite._member_map_.values()))
    closest = GeoSatellite(min(satellites, key=lambda x:abs(x-longitude)))
    if closest == GeoSatellite.AORWSC:   #: single regional beam only
        if latitude >= 15.0 or latitude <= -45.0:
            if longitude >= -27.0:
                return GeoSatellite.EMEA
            return GeoSatellite.AMER
    # elif closest == GeoSatellite.MEAS:   #: not all beams lit
    #     if latitude <= -4.5:
    #         if longitude >= 63.5:
    #             return GeoSatellite.APAC
    #         return GeoSatellite.EMEA
    #     elif latitude >= 40.9:
    #         if longitude <= 45.0:
    #             return GeoSatellite.EMEA
    #         if longitude >= 82.5:
    #             return GeoSatellite.APAC
    #     elif longitude >= 63.5:
    #         if latitude <= -4.0 or latitude >= 30.0:
    #             return GeoSatellite.APAC
    return closest


def get_satellite_location(modem_location: ModemLocation,
                           geobeam: 'GeoBeam|None' = None,
                           ) -> SatelliteLocation:
    """Derives the azimuth and elevation of the nearest satellite.
    
    If not provided the current GeoBeam, derives the closest satellite from
    the location provided.
    
    Args:
        modem_location (ModemLocation): The modem's Location object.
        geobeam (GeoBeam): The GeoBeam, if known. If `None` it will be
            assumed from fixed locations of satellites.
    
    Returns:
        `SatelliteLocation` including azimuth, elevation from the modem.
    
    """
    # internal helper functions
    def location_to_point(latitude: float,
                        longitude: float,
                        altitude: float,
                        ) -> _PointLocation:
        """Converts lat/lon/alt to point location."""
        lat_rad = latitude * math.pi / 180.0
        lon_rad = longitude * math.pi / 180.0
        radius = get_geographic_radius(lat_rad)
        clat = get_geocentric_latitude(lat_rad)
        cos_lon = math.cos(lon_rad)
        sin_lon = math.sin(lon_rad)
        cos_lat = math.cos(clat)
        sin_lat = math.sin(clat)
        x = radius * cos_lon * cos_lat
        y = radius * sin_lon * cos_lat
        z = radius * sin_lat
        cos_glat = math.cos(lat_rad)
        sin_glat = math.sin(lat_rad)
        nx = cos_glat * cos_lon
        ny = cos_glat * sin_lon
        nz = sin_glat
        x += altitude * nx
        y += altitude * ny
        z += altitude * nz
        return _PointLocation(x, y, z, radius, nx, ny, nz)

    def get_geographic_radius(lat_rad: float) -> float:
        """Adjust radius for earth shape."""
        equatorial = 6378137.0
        polar = 6356752.3
        cos = math.cos(lat_rad)
        sin = math.sin(lat_rad)
        t1 = equatorial**2 * cos
        t2 = polar**2 * sin
        t3 = equatorial * cos
        t4 = polar * sin
        return math.sqrt((t1 * t1 + t2 * t2) / (t3 * t3 + t4 * t4))

    def get_geocentric_latitude(lat_rad: float) -> float:
        """Derives the geocentric latitude."""
        e2 = 0.00669437999014   # first eccentricity squared, constant
        clat = math.atan((1.0 - e2) * math.tan(lat_rad))
        return clat

    def rotate_globe(b: SatelliteLocation, a: ModemLocation, b_radius: float):
        """Rotate the globe for vector alignment."""
        brp = location_to_point(b.latitude, b.longitude - a.longitude, b.altitude)
        alat = get_geocentric_latitude(-a.latitude * math.pi / 180.0)
        acos = math.cos(alat)
        asin = math.sin(alat)
        bx = (brp.x * acos) - (brp.z * asin)
        by = brp.y
        bz = (brp.x * asin) + (brp.z * acos)
        return _PointLocation(bx, by, bz, b_radius, 0.0, 0.0, 0.0)

    def normalize_vector(b: _PointLocation, a: _PointLocation):
        """Normalize the difference between vectors."""
        dx = b.x - a.x
        dy = b.y - a.y
        dz = b.z - a.z
        dist2 = dx**2 + dy**2 +dz**2
        if dist2 == 0:
            return None
        dist = math.sqrt(dist2)
        return _PointLocation(dx/dist, dy/dist, dz/dist, 1.0, 0.0, 0.0, 0.0)

    azimuth = None
    elevation = None
    if isinstance(geobeam, GeoBeam):
        satellite_name = geobeam.name.split('_')[0]
        satellite = GeoSatellite[satellite_name]
    else:
        satellite = get_closest_satellite(modem_location.latitude,
                                          modem_location.longitude)
    # modem and satellite Cartesian location
    mc = modem_location
    sc = SatelliteLocation(name=satellite.name,
                           longitude=satellite.value, 
                           altitude=GEOSTATIONARY_DISTANCE_M,
                           geobeam=geobeam)
    # modem and satellite Point location
    mp = location_to_point(mc.latitude, mc.longitude, mc.altitude)
    sp = location_to_point(sc.latitude, sc.longitude, sc.altitude)
    ref_point = rotate_globe(sc, mc, sp.radius)
    if ref_point.z**2 + ref_point.y**2 > 1.0e-6:
        theta = math.atan2(ref_point.z, ref_point.y) * 180.0 / math.pi
        azimuth = 90.0 - theta
        if azimuth < 0.0:
            azimuth += 360.0
        if azimuth > 360.0:
            azimuth -= 360.0
        bma = normalize_vector(sp, mp)   # Bayesian model averaging
        if isinstance(bma, _PointLocation):
            elevation = (90.0 - (180.0 / math.pi) * math.acos(
                bma.x * mp.nx + bma.y * mp.ny + bma.z * mp.nz))
    sc.azimuth = round(azimuth, 1)
    sc.elevation = round(elevation, 1)
    return sc

# Below is parked for potential future use

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
