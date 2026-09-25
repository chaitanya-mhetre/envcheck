# Changelog

## Unreleased
- New `http` / `https` service type: `GET` a URL and check the status (default any 2xx, or `expect_status`,
  one code or a list) and an optional body substring (`expect_body`). Hand-written HTTP/1.0 over asyncio
  streams (TLS via `ssl`), a single deadline for the whole exchange, body read capped at 64 KB, redirects not followed,
  and URLs from env vars (and query strings) never printed.

## 0.1.0 — 2026-09-25 (unreleased, not on PyPI)
- `envcheck.yaml` schema (strict, versioned).
- Checks: tool + version constraint (PEP 440, `^`, `~`, `*`), Docker daemon, TCP, Redis (RESP AUTH/PING, no
  dependency), Postgres (`SELECT 1` via optional psycopg), free port, env var presence/pattern, `.env` drift, files.
- Concurrent runner with per-check timeouts; crashes and timeouts become failures.
- Output: table, JSON, JUnit XML. `--ci` mode (skips, strict warnings).
- `envcheck init` drafts a config from pyproject.toml, package.json, docker-compose and .env.example.
- Service plugins via the `envcheck.services` entry-point group.
