"""EXAMPLE: Sends the NIMO modem's location periodically.

*Note that message encoding is sub-optimal using 4 bytes each for lat/lon.*

"""
import logging
import os
import time

from pynimomodem.nimomodem import Serial, NimoModem, MessageState

SERIAL_PORT = os.getenv('SERIAL_PORT', '/dev/ttyUSB0')
BEACON_INTERVAL = 15   # minutes


logging.basicConfig(format='%(asctime)s [%(levelname)s]: %(message)s',
                    level=logging.INFO)


def main():
    modem = NimoModem(Serial(SERIAL_PORT))
    if not modem.is_connected():
        modem.await_boot(30)
    if not modem.is_connected() or not modem.initialize():
        raise ConnectionError
    while True:
        logging.info('Getting location to send beacon...')
        location = modem.get_location()
        logging.info('Sending lat/lon from location: %s', location)
        message_payload = b'\x80\x01'   # SIN 128, MIN 1
        lat_int = int(location.latitude * 60000)
        lon_int = int(location.longitude * 60000)
        message_payload += lat_int.to_bytes(4, 'big', signed=True)
        message_payload += lon_int.to_bytes(4, 'big', signed=True)
        message_name = modem.send_data(message_payload)
        complete = False
        while not complete:
            tx_queue = modem.get_mo_message_states()
            for msg in tx_queue:
                if msg.name == message_name:
                    if msg.state >= MessageState.TX_COMPLETE:
                        if msg.state == MessageState.TX_FAILED:
                            logging.error('Message %s FAILED!', message_name)
                        else:
                            logging.info('Beacon sent!')
                        complete = True
                        break   # for loop
            if not complete:
                time.sleep(5)   # wait a frame length before checking again
        logging.info('Next beacon in %d minutes', BEACON_INTERVAL)
        time.sleep(BEACON_INTERVAL * 60)


if __name__ == '__main__':
    main()
