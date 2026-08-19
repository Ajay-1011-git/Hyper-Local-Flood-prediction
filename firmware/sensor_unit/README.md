# ESP32 sensor unit firmware

`sensor_unit.ino` (T1B.10) is not yet implemented. WiFi credentials belong in
a git-ignored `secrets.h` in this directory — never commit them.

Before writing connection code, verify the current ESP32 Arduino core's WiFi
and HTTPClient library API in-session; method signatures have changed
across core versions.
