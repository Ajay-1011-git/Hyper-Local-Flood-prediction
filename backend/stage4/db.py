"""Database & Redis connection layer — T4A.0 dependency, not yet built.

Not yet implemented. Will mirror Stage 1B/2/3's db.py pattern
(`get_db_session()`, `get_redis_client()`) once a task actually needs to
persist an `Alert` or cache something -- not built speculatively ahead of
that need, per this project's established convention (Stage 3's T3.0/
T3.6 did the same: db.py started as a stub and grew only what T3.6
actually required).
"""
