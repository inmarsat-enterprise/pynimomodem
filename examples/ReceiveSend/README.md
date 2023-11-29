# Receive and Send Messages via Satellite

Checks periodically for Mobile-Terminated message(s) either by polling the modem
periodically or triggered by a GPIO interrupt
(e.g. Raspberry Pi GPIO or a microcontroller running Micropython).

Upon receiving a query, if the codec SIN is 128 and codec MIN is 1,
it sends a response to echo the query with SIN 128 MIN 2.

Also includes an example of using Quectel modem **URC** codes.