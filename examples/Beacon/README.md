# NIMO modem Beacon Example

On startup and every 15 minutes, the modem's location is queried and then
sent as a 10-byte message consisting of:

* `0x80` Codec service type (aka **SIN**) implying a "beacon" service
* `0x01` Codec message type (aka **MIN**) implying a location report with
latitude and longitude each 4 bytes
* `<latitude>` 4 bytes signed 32-bit integer value
* `<longitude>` 4 bytes signed 32-bit integer value

Also will wait up to 30 seconds if no modem response on start-up.
And raises a `ConnectionError` if it cannot connect to the modem.