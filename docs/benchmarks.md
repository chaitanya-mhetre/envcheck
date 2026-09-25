# Measurements

## Wall time for this repo's own `envcheck.yaml` (measured 2026-09-25)
Twelve checks: 4 tools, the Docker daemon, Postgres (login + `SELECT 1`), Redis (AUTH + PING), 2 env vars, `.env` drift, 2 files.
The services were local containers from `docker-compose.yml`.

Command: `.venv/bin/envcheck > /dev/null`, run 5 times. Environment: Linux 7.0 laptop, 16 cores, Python 3.12.14.

| Run (sorted) | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| Wall time (ms) | 274 | 274 | 275 | 291 | 313 |

That includes Python start-up and imports. Checks run concurrently, so the total is close to the slowest check
(`docker info` and `docker compose version`), not the sum. Through `uv run` it was about 420 ms.
