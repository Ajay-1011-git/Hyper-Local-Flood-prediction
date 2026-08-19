# ESP32 sensor unit firmware — T1B.10

Status: **code written, blocked on real hardware for VERIFY.** T1B.10's
definition of done requires flashing to a physical ESP32 + HC-SR04 and
pasting real serial-monitor output (WiFi connect, real sensor readings,
successful POSTs over 5+ consecutive readings) — that step needs the
actual hardware in hand, which this environment doesn't have.

Every non-trivial API call in `sensor_unit.ino` was checked against the
current `arduino-esp32` core's actual source on GitHub (latest tagged
release: **3.3.11**) rather than assumed from memory — including the
less obvious ones: `getLocalTime()`'s default 5000ms timeout argument
(`Arduino.h`: `bool getLocalTime(struct tm *info, uint32_t ms = 5000)`)
and `Print`'s `struct tm*`-accepting overload used for the sync-time log
line. A full *compile* check (not just reading source) was attempted via
`arduino-cli` — the ESP32 toolchain download was installed up to the
point of fetching the actual Xtensa compiler binary, which timed out
repeatedly at the network layer in this sandboxed environment (the host
itself was reachable; the asset transfer wasn't) — so this hasn't been
build-verified by a compiler, only by careful manual review against real
API signatures. Worth a real `arduino-cli compile` or Arduino IDE
verify-only build before flashing, in an environment where that download
succeeds.

## Setup

1. Arduino IDE, board manager URL for ESP32 support (if not already
   installed): `https://espressif.github.io/arduino-esp32/package_esp32_index.json`
   — install the `esp32` boards package (confirmed current release
   3.3.11 as of writing; check for a newer one before flashing, since
   this firmware assumes that core's `HTTPClient`/`WiFi` API shapes).
2. Board: whichever ESP32 DevKit board you have (e.g. "ESP32 Dev Module").
3. No external libraries needed — `WiFi.h` and `HTTPClient.h` ship with
   the ESP32 core; HC-SR04 reading uses plain `pulseIn()`, not a separate
   ultrasonic-sensor library.
4. Copy `secrets.h.example` to `secrets.h` in this same directory and
   fill in your real WiFi credentials, the Stage 1B server's reachable
   URL, `SENSOR_INGEST_TOKEN` (must match `backend/stage1b/.env`), and a
   `SENSOR_ID`. **`secrets.h` is git-ignored — never commit it.**
5. Wire the HC-SR04: `VCC`→5V, `GND`→GND, `TRIG`→GPIO26, `ECHO`→GPIO27
   (through a voltage divider or level shifter — the HC-SR04's ECHO pin
   outputs 5V, and most ESP32 GPIOs are not 5V-tolerant; a simple
   resistor divider, e.g. 1kΩ/2kΩ, brings it down to ~3.3V).
6. Flash, open the Serial Monitor at 115200 baud.

## What to paste back once flashed (completes T1B.10's VERIFY)

- WiFi connection log (SSID, resulting IP).
- NTP time sync confirmation.
- At least 5 consecutive cycles of: a real distance reading (not 0.00 or
  NaN — indicates the sensor is actually wired and responding), the JSON
  POST body sent, the real HTTP status code and response body from the
  server (expect `200` and the echoed `SensorReading` JSON, matching
  T1B.11's verified `POST /api/sensor/reading` behavior).
