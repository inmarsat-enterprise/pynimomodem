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