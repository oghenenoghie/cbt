# Windows Desktop Application

Electron + TypeScript desktop client sharing UI components and API contracts with the web application where practical.

Initial responsibilities:
- managed Windows installation and updates;
- school/device registration;
- secure download and verification of assigned exam packages;
- offline student examination;
- local SQLite persistence and crash recovery;
- signed submission queue and idempotent synchronization;
- clear connectivity and sync status.

Do not store API secrets in the desktop bundle. Treat the client device as untrusted and validate all submissions on the server.
