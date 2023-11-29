"""Listens for a query and echos back a response to the sender."""
import logging
import os
import time
from threading import Timer

from pynimomodem import (
    EventNotification,
    MessageState,
    NimoModem,
    NimoModemError,
    UrcCode,
    UrcControl,
)

try:   # Raspberry Pi GPIO
    from gpiozero import DigitalInputDevice
    from gpiozero.pins.pigpio import PiGPIOFactory
    GPIO = 'gpiozero'
except ImportError:
    try:   # Micropython microcontroller GPIO
        from machine import Pin
        GPIO = 'machine'
    except ImportError:   # No GPIO available
        GPIO = None

SERIAL_PORT = os.getenv('SERIAL_PORT', '/dev/ttyUSB0')
MODEM_EVENT_PIN = os.getenv('MODEM_EVENT_PIN')
POLL_INTERVAL = 5

logging.basicConfig(format='%(asctime)s [%(levelname)s]: %(message)s',
                    level=logging.INFO)


def main():
    modem = NimoModem(SERIAL_PORT)
    if not modem.is_connected():
        logging.warning('Retrying supported baud rates')
        modem.retry_baudrate()
        if not modem.is_connected():   # baudrate wasn't the issue
            logging.warning('Check that modem is connected and powered')
            modem.await_boot(30)
    if not modem.initialize():
        raise ConnectionError
    logging.info('Connected to NIMO!')
    manufacturer = modem.get_manufacturer()
    polling: bool = not (GPIO and MODEM_EVENT_PIN)
    timer = None
    
    def poll_modem(delay: int = POLL_INTERVAL):
        """Starts a timer to poll the modem for events."""
        logging.debug('Starting timer %d seconds', delay)
        timer = Timer(delay, event_trigger)
        timer.name = 'ModemPoller'
        timer.daemon = True
        timer.start()
    
    def receive_message():
        """Processes the new message received Over-The-Air."""
        for meta in modem.get_mt_message_states():
            rx_message = modem.get_mt_message(meta.name)
            if rx_message.codec_sin == 128 and rx_message.codec_min == 1:
                logging.info('Echoing test message (size = %d)',
                             rx_message.length)
                echo = b'\x80\x02' + rx_message.payload[2:]
                send_response(echo)
    
    def send_response(data: bytes):
        """Sends response data Over-The-Air."""
        message_name = modem.send_data(data)
        # Checking the Tx queue to clear it, could be triggered by GPIO
        while message_name:
            time.sleep(5)
            for meta in modem.get_mo_message_states():
                if (meta.name == message_name and
                    meta.state >= MessageState.TX_COMPLETE):
                    logging.info('Echo complete (%s)', message_name)
                    message_name = None
                    break
    
    def event_trigger():
        """Checks and processes modem events when triggered by input or timer"""
        message_waiting = False
        try:
            if 'quectel' in manufacturer.lower():
                while True:
                    urc = modem.get_urc()
                    if not urc:
                        break
                    logging.info('Found URC: %s', UrcCode.name)
                    if urc == UrcCode.RX_END:
                        message_waiting = True
            else:
                events = modem.get_events_asserted_mask()
                if events and EventNotification.MESSAGE_MT_RECEIVED:
                    logging.info('Found events: %s',
                                EventNotification.get_events(events))
                    message_waiting = True
            if message_waiting:
                receive_message()
            else:
                logging.info('No message found from event %s',
                            'poll' if polling else 'trigger')
        except NimoModemError:
            # Serial parsing errors might prevent an event from being processed
            logging.error('Some parsing error occured - checking for messages')
        finally:
            if polling:
                poll_modem()

    # setup events to capture
    if 'quectel' in manufacturer.lower():
        event_mask: int = (UrcControl.MESSAGE_MT_RECEIVED |
                           UrcControl.MESSAGE_MO_COMPLETE)
        modem.set_urc_ctl(event_mask)
    else:
        event_mask: int = (EventNotification.MESSAGE_MT_RECEIVED |
                           EventNotification.MESSAGE_MO_COMPLETE)
        modem.set_event_mask(event_mask)
    
    # configure event capture by polling or interrupt
    if polling:
        modem_event_pin = None
        poll_modem()
    elif GPIO == 'gpiozero' and MODEM_EVENT_PIN:
        modem_event_pin = DigitalInputDevice(int(MODEM_EVENT_PIN),
                                            pin_factory=PiGPIOFactory)
        modem_event_pin.when_activated = event_trigger
    elif GPIO == 'machine' and MODEM_EVENT_PIN:
        modem_event_pin = Pin(int(MODEM_EVENT_PIN), Pin.IN)
        modem_event_pin.irq(event_trigger)
    
    notified_start = False
    start_time = int(time.time())
    while True:
        if not notified_start:
            if not timer:
                logging.info('Waiting for notification event trigger...')
            else:
                logging.info('Polling modem every %d seconds for events',
                             POLL_INTERVAL)
            notified_start = True
        if not polling and int(time.time()) - start_time == 30:
            logging.info('Still waiting...')
            start_time = int(time.time())


if __name__ == '__main__':
    main()
