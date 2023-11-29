from pynimomodem.constants import GeoBeam, GeoSatellite
from pynimomodem.location import (
    ModemLocation,
    SatelliteLocation,
    get_closest_satellite,
    get_location_from_nmea_data,
    get_satellite_location,
    validate_nmea,
)

test_loc = ('$GPRMC,005249.000,A,4517.1082,N,07550.9113,W,0.24,0.00,231123,,,A,V*0B\n'
            '$GPGGA,005249.000,4517.1082,N,07550.9113,W,1,06,1.7,128.5,M,-34.3,M,,0000*62\n'
            '$GPGSA,A,3,02,07,21,14,08,27,,,,,,,2.8,1.7,2.2,1*2D')


def test_validate_nmea():
    test_sentence = '$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A'
    assert validate_nmea(test_sentence)
    assert not validate_nmea(test_sentence.replace('*6A', '*BB'))
    assert not validate_nmea(test_sentence[:-3])


def test_location_from_nmea():
    location = get_location_from_nmea_data(test_loc)
    assert isinstance(location, ModemLocation)
    assert round(location.latitude, 5) == 45.01667
    assert round(location.longitude, 5) == -75.08333
    assert round(location.altitude, 1) == 128.5
    assert location.fix_type == 3
    assert location.fix_quality == 1
    assert round(location.speed, 1) == 0.2
    assert location.heading == 0.0
    assert round(location.pdop, 1) == 2.8
    assert round(location.hdop, 1) == 1.7
    assert round(location.vdop, 1) == 2.2
    assert location.satellites == 6
    assert location.timestamp == 1700700769
    assert location.time_iso == '2023-11-23T00:52:49Z'
    assert len(str(location)) == 209


def test_closest_satellite():
    modem_location = get_location_from_nmea_data(test_loc)
    closest = get_closest_satellite(modem_location.latitude,
                                    modem_location.longitude)
    assert isinstance(closest, GeoSatellite)
    assert closest.name == 'AMER'


def test_sat_location():
    modem_location = get_location_from_nmea_data(test_loc)
    geobeam = GeoBeam(16)
    satellite_location = get_satellite_location(modem_location, geobeam)
    assert isinstance(satellite_location, SatelliteLocation)
    assert satellite_location.azimuth == 211.0
    assert satellite_location.elevation == 33.4
