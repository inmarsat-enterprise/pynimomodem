# pynimomodem

A Python implementation of the [Viasat](www.viasat.com)
NIMO modem interface for satellite IoT.

NIMO stands for **Non-IP Modem Orbcomm** waveform
and represents a family of low cost satellite data modems that use network
protocols developed by [ORBCOMM](www.orbcomm.com)
including [IsatData Pro](https://www.inmarsat.com/en/solutions-services/enterprise/services/isatdata-pro.html) and its successor, OGx.

These ORBCOMM protocols can operate over the Viasat L-band global network in
cooperation with a varietry of authorized Viasat IoT service partners, and
are intended for event-based remote data collection and device control.

Example NIMO modems available:
* [ORBCOMM ST2100](https://www.orbcomm.com/en/partners/iot-hardware/st-2100)
* [Quectel CC200A-LB](https://www.quectel.com/product/cc200a-lb-satellite-communication-module)
* [uBlox UBX-S52](https://content.u-blox.com/sites/default/files/documents/UBX-R52-S52_ProductSummary_UBX-19026227.pdf)

## Additional Information

* [API Documentation](https://inmarsat-enterprise.github.io/pynimomodem/)

> [!NOTE]
> Obsoletes/replaces the Inmarsat `idpmodem` project, when combined with the
> [`pynimcodec`](github.com/inmarsat-enterprise/pynimcodec) library.

## Installation

Example using pip, on a Linux-based platform including `PySerial` dependency:
```
pip install 'pynimomodem'
```

## Background

### Overview

*IsatData Pro* (**IDP**)is a store-and-forward satellite messaging technology
with flexible message sizes:

* up to 6400 bytes Mobile-Originated (aka **MO**, From-Terminal, *Return*)
* up to 10000 bytes Mobile-Terminated (aka **MT**, To-Terminal, *Forward*)

***Message***s are sent to or collected from a ***Mobile*** using its globally
unique *Mobile ID*,
transacted through a ***Mailbox*** that provides authentication, encryption and
data segregation for cloud-based or enterprise client applications via a
REST **Messaging API**.

Data sources and controls in the field are interfaced to a modem using a serial
interface with *AT commands* to send and receive messages, check network status,
and optionally use the built-in *Global Navigation Satellite System* (GNSS)
receiver to determine location-based information.

The first byte of the message is referred to as the
*Service Identification Number* (**SIN**) where values below 16 are reserved
for system use.  SIN is intended to capture the concept of embedded
microservices used by an application.

The second byte of the message can optionally be defined as the
*Message Identifier Number* (**MIN**) intended to support remote operations 
within each embedded microservice with defined binary formatting.
The MIN concept also supports the optional *Message Definition File* feature
allowing an XML file to be applied which presents a JSON-tagged message
structure on the network API.

### Modem Concept of Operation

1. Upon power-up or reset, the modem first acquires its location using 
Global Navigation Satellite Systems (GNSS).
1. After getting its location, the modem tunes to the correct frequency, then
registers on the network.  Once registered it can communicate on the
network.
1. MO messages are submitted by a microcontroller or IoT Edge device, which
then must monitor progress until the message is complete (either delivered or
timed out/failed due to blockage). Completed messages must be cleared from the
modem transmit queue by querying state(s) either periodically or when prompted
by the modem's event notification pin if configured.
1. MT messages that arrive are stored in the receive queue and the Edge device
queries for *New* MT messages periodically or when prompted by the modem's
event notification pin if configured.
1. Network acquisition status can also be queried using AT commands.
1. If the modem cannot find the target frequency it begins to search for other
frequencies from a configuration map in its non-volatile memory. It will cycle
through beam acquisition attempts for a period of time before falling back to
a globally-accessible *Bulletin Board* frequency where it may need to download
a new network configuration before re-attempting. Bulletin board downloads
typically take less than 15 minutes but can take longer in low signal or high
interference locations. A modem should not be powered off during Bulletin
Board download.
1. Prolonged obstruction of satellite signal will put the modem into *blockage*
state from which it will automatically try to recover based on an algorithm
influenced by its *power mode* setting.