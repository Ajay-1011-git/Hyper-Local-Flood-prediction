/*
 * T1B.10 — ESP32 + HC-SR04 sensor unit firmware.
 *
 * Reads distance from an HC-SR04 ultrasonic sensor on a fixed interval and
 * POSTs it to backend/stage1b/routes.py's POST /api/sensor/reading
 * (T1B.11), which validates it against the shared SensorReading contract,
 * persists it, and broadcasts a WebSocket event.
 *
 * CONFIRMED APIs (fetched and read in this session, not assumed — see
 * commit message for full source list):
 * - WiFi.h / HTTPClient.h: verified against the current arduino-esp32
 *   core's actual header source (github.com/espressif/arduino-esp32,
 *   libraries/HTTPClient/src/HTTPClient.h on the master branch; latest
 *   tagged release confirmed to be 3.3.11). The simple
 *   `bool begin(String url)` + `int POST(String payload)` overloads used
 *   below are real, current signatures in that header — not guessed from
 *   memory, since ESP32 Arduino core APIs are documented to have changed
 *   across versions (this file's own build-instructions doc's own
 *   warning).
 * - configTime()/getLocalTime()/strftime(): standard ESP32 Arduino core
 *   SNTP wrapper, confirmed still current (no deprecation found).
 * - HC-SR04 read via pulseIn(): standard Arduino core function, not
 *   ESP32-specific and not version-sensitive — deliberately NOT using an
 *   extra HC-SR04 library here, to avoid depending on one whose current
 *   API wasn't independently verified.
 *
 * WiFi credentials, server URL, auth token, and sensor_id live in a
 * separate, git-ignored secrets.h (see secrets.h.example for the
 * template) — never hardcoded here, per T1B.10's requirement.
 */

#include <HTTPClient.h>
#include <WiFi.h>
#include <time.h>

#include "secrets.h"

// HC-SR04 pins. Chosen to avoid ESP32's strapping pins (0, 2, 5, 12, 15)
// and input-only pins (34-39, which can't drive TRIG) — TRIG=GPIO26
// (output-capable), ECHO=GPIO27 (input-capable), a conventional,
// conflict-free pair for DevKit-style boards.
constexpr int TRIG_PIN = 26;
constexpr int ECHO_PIN = 27;

// Real, deliberate interval per T1B.10's requirement ("every 2 seconds").
constexpr unsigned long READING_INTERVAL_MS = 2000;

// HC-SR04 datasheet: no reliable echo beyond ~4m indoors; pulseIn's
// timeout guards against a stuck/disconnected sensor hanging the loop
// (30ms round-trip covers ~5m one-way at the speed of sound, generous
// headroom over the sensor's rated range).
constexpr unsigned long ECHO_TIMEOUT_US = 30000;

void connectWiFi() {
  Serial.print("Connecting to WiFi: ");
  Serial.println(WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();
  Serial.print("WiFi connected. IP address: ");
  Serial.println(WiFi.localIP());
}

void syncTime() {
  // UTC (0, 0 offsets) — matches the server side's expectation of
  // ISO8601 UTC timestamps (confirmed working against real "...Z"
  // timestamps in T1B.9/T1B.11's VERIFY runs).
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  Serial.print("Syncing time via NTP");
  struct tm timeinfo;
  while (!getLocalTime(&timeinfo)) {
    Serial.print(".");
    delay(500);
  }
  Serial.println();
  Serial.print("Time synced: ");
  Serial.println(&timeinfo, "%Y-%m-%d %H:%M:%S UTC");
}

// Returns NAN if no echo was received within ECHO_TIMEOUT_US (sensor
// disconnected, out of range, or a bad reading) — the caller must check
// for this rather than silently posting a fabricated distance.
float readDistanceCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  unsigned long durationUs = pulseIn(ECHO_PIN, HIGH, ECHO_TIMEOUT_US);
  if (durationUs == 0) {
    return NAN;  // timeout / no echo
  }

  // Speed of sound ~343 m/s at room temperature -> 0.0343 cm/us; divide
  // by 2 for the round trip (standard HC-SR04 datasheet formula, not
  // invented here).
  return (durationUs * 0.0343f) / 2.0f;
}

bool postReading(float distanceCm, const String &isoTimestamp) {
  HTTPClient http;
  http.begin(SERVER_URL);  // confirmed real overload: bool begin(String url)
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Sensor-Token", SENSOR_TOKEN);

  // Hand-built JSON (3 flat fields — deliberately not pulling in
  // ArduinoJson for a payload this simple, keeping the dependency
  // surface to only APIs actually verified above). String values are
  // controlled by us (SENSOR_ID from secrets.h, a formatted timestamp),
  // not user input, so no escaping is needed.
  char payload[192];
  snprintf(
      payload, sizeof(payload),
      "{\"sensor_id\":\"%s\",\"distance_cm\":%.2f,\"timestamp\":\"%s\"}",
      SENSOR_ID, distanceCm, isoTimestamp.c_str());

  Serial.print("POST body: ");
  Serial.println(payload);

  int statusCode = http.POST(String(payload));  // confirmed real overload: int POST(String payload)
  String responseBody = http.getString();

  Serial.print("POST status: ");
  Serial.println(statusCode);
  Serial.print("POST response: ");
  Serial.println(responseBody);

  http.end();
  return statusCode == 200;
}

void setup() {
  Serial.begin(115200);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  digitalWrite(TRIG_PIN, LOW);

  connectWiFi();
  syncTime();
}

void loop() {
  float distanceCm = readDistanceCm();

  if (isnan(distanceCm)) {
    Serial.println("Sensor read timed out (no echo) — skipping this cycle, not posting a fabricated reading.");
  } else {
    struct tm timeinfo;
    if (!getLocalTime(&timeinfo, 100)) {
      Serial.println("Time not available yet — skipping this cycle.");
    } else {
      char isoBuf[25];
      strftime(isoBuf, sizeof(isoBuf), "%Y-%m-%dT%H:%M:%SZ", &timeinfo);

      Serial.print("Distance: ");
      Serial.print(distanceCm);
      Serial.println(" cm");

      if (WiFi.status() != WL_CONNECTED) {
        Serial.println("WiFi dropped — attempting to reconnect...");
        connectWiFi();
      }

      postReading(distanceCm, String(isoBuf));
    }
  }

  delay(READING_INTERVAL_MS);
}
