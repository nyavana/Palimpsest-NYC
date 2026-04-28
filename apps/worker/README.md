# Palimpsest Worker

Background worker for scheduled ingestion and other long-running tasks.

Shares code with `apps/api` (imports from `app.*`), different entrypoint.
Runs inside the same Docker image, invoked via:

```bash
python -m worker.main
```
