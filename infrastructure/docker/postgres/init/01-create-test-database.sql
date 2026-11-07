-- Runs once, when the Postgres data volume is first created.
-- The test suite drops every table it creates, so it gets its own database and can never
-- touch development data (backend/api/tests/conftest.py refuses databases not ending in _test).
CREATE DATABASE cbt_test;
