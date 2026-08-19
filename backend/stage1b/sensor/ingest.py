"""Sensor reading ingestion: validate, persist, broadcast — T1B.11.

Not yet implemented. Depends on T1B.1. POST /api/sensor/reading, wired in
routes.py, must reject requests whose header doesn't match
SENSOR_INGEST_TOKEN with 401, and broadcast accepted readings via
WebSocket on /ws/site/{site_id}.
"""
