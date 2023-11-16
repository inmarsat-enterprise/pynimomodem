from pynimomodem.crcxmodem import apply_crc, validate_crc


def test_apply_crc():
    """"""
    assert apply_crc('AT%CRC=0') == 'AT%CRC=0*BBEB'


def test_validate_crc():
    """"""
    assert validate_crc('AT%CRC=0*BBEB') is True
    assert validate_crc('\r\nERROR\r\n*84D9\r\n') is True
