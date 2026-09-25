# envcheck

Declare the dev environment a project needs in one file, then check it with one command, locally or in CI.
It's a generic, declarative `doctor` command, in the spirit of `flutter doctor`.

```
$ envcheck
   check                    result                                              fix
✔  tool:python              python 3.12.14 (wanted >=3.12)
✔  tool:docker compose      docker compose 5.3.1 (wanted *)
✔  docker:daemon            Docker daemon running (server 29.6.2)
✔  service:postgres         Postgres 16 accepted a login and answered SELECT 1
✔  service:redis            Redis at 127.0.0.1:56385 answered PONG
✔  env:drift                .env matches .env.example (2 keys)
...
12 pass, 0 warn, 0 fail, 0 skip
```

> Status: 0.1.0, not published to PyPI. **Several `envcheck` packages probably exist already, so check the PyPI name before publishing
> (and rename if needed).**

## Problem
New contributors lose hours because Python is 3.10 instead of 3.12, Docker isn't running, Postgres isn't reachable, port 8000
is taken, or `DATABASE_URL` is missing. READMEs describe the requirements, but nothing checks them.

## Why it exists
- **mise/asdf** install and pin tool versions, but they don't check services or env vars.
- **devcontainers/Nix** give fully reproducible environments, but they're heavy.
- **dotenv-linter**, **envalid** and **pydantic-settings** only validate env vars.

envcheck **installs nothing**. It checks everything a project needs and tells you how to fix each problem. It's mainly a learning
project (async I/O, subprocesses, network protocols, plugins) with a small practical niche: a `make doctor` for every repo.

## Architecture
```
envcheck.yaml ─► Config (pydantic, strict, versioned) ─► plan() ─► [Check, Check, ...]
                                                              │
                  service types: tcp | redis | postgres | <entry-point plugins>
                                                              │
                     async runner (asyncio.gather, semaphore, per-check timeout)
                                                              │
                        reporters: table (rich) | json | junit xml
```
- **Checks are classes** with `kind`, `id` and `async run()`. The runner turns timeouts and crashes into `fail`, so one bad check
  can't hang or kill the run.
- **Service health versus an open port:** `tcp` proves something is listening. `redis` speaks RESP (optional `AUTH`, then `PING`) with no
  client library, and `postgres` logs in and runs `SELECT 1` (through the optional `psycopg` extra; without it, it falls back to TCP and returns a warning).
- **Version parsing:** each known tool has its own command and regex (`java` prints to stderr, `kubectl` needs `--client`). Unknown tools fall
  back to `<tool> --version`.

## Features
- Tools with constraints: PEP 440 (`>=3.12`, `>=1,<2`), npm-style `^20` / `~1.9`, bare `3.12` (any 3.12.x), and `*`.
- A Docker daemon check, with a specific hint when the problem is docker-group permissions.
- Postgres, Redis and TCP services. Targets come from a literal URL, an env var (`url_env`/`dsn_env`), or host + port.
- Free ports (with an `lsof`/`ss` hint), env var presence and regex, `.env` vs `.env.example` drift, and required files.
- `.env` values are merged in, but the real environment wins.
- **Secret values are never printed**: `DATABASE_URL is set`, never its value. Tests enforce this.
- `--ci` skips listed kinds or ids and makes warnings fail. There's also `--format json|junit` and `--verbose`.
- `envcheck init` drafts a config from `pyproject.toml`, `uv.lock`, `package.json`, `docker-compose.yml` and `.env.example`,
  and prints every detection it made.

## Tech stack
Python 3.12+, asyncio (`create_subprocess_exec`, `open_connection`), Typer, pydantic v2, `packaging`, rich, and optionally psycopg 3.

## Quick start
```bash
uvx envcheck init        # after publishing; for now: uv sync && uv run envcheck init
uvx envcheck
```

## API usage
```yaml
# envcheck.yaml
version: 1
tools: {python: ">=3.12", uv: "*", docker: "*", node: "^20"}
docker_daemon: true
services:
  db:    {type: postgres, dsn_env: DATABASE_URL}
  cache: {type: redis, url_env: REDIS_URL}
  api:   {type: tcp, host: localhost, port: 8080, timeout_s: 2}
ports_free: [8000]
env:
  required: [DATABASE_URL, REDIS_URL]
  patterns: {DATABASE_URL: "^postgres(ql)?://"}
  dotenv: .env
  drift: {example: .env.example, actual: .env}
files: [alembic.ini]
ci: {skip: [docker_daemon, ports_free], strict: true}
```
```
envcheck [--config FILE] [--ci] [--format table|json|junit] [--verbose]
envcheck init [--force]
envcheck list-checks
```
Exit codes: `0` ready, `1` failures (or warnings in `--ci` strict mode), `2` bad config.

**Plugins:** add a service type from another package:
```toml
[project.entry-points."envcheck.services"]
mongo = "mypkg.checks:MongoCheck"     # subclass envcheck.checks.services.ServiceCheck
```

## Demo
This repo checks itself. `make services && cp .env.example .env && make doctor` produces the output at the top of this README.
`examples/fastapi-project.envcheck.yaml` shows a typical backend service.

## Testing
`make check` runs ruff, `mypy --strict` and 61 tests:
- 16 real `--version` output fixtures and constraint tests
- checks against fake subprocess output and local asyncio TCP servers (a fake Redis replying `+PONG` / `-NOAUTH`)
- runner timeout, crash and concurrency tests
- JUnit/table reporter tests, CLI tests, `init` detection tests
- 3 integration tests against real Postgres 16 and Redis 7 from `docker-compose.yml` (ports 55438/56385); these skip with a
  stated reason when the containers aren't running

## Deployment
PyPI via trusted publishing on a `v*` tag (`.github/workflows/release.yml`, not run yet). CI runs `envcheck --ci --format junit` on
this repo and publishes the result as a GitHub check. That workflow hasn't run on GitHub yet.

## Security
- No `shell=True`: commands are argv lists.
- Env var values and DSNs are never echoed. Postgres errors show psycopg's first line, which names host/user but not the password.
- The config is parsed with `yaml.safe_load` and a strict schema, and unknown keys are rejected.

## Performance
Measured on one laptop: 274–313 ms wall time for this repo's 12 checks, including Python start-up.
See [docs/benchmarks.md](docs/benchmarks.md).

## Engineering trade-offs
- **Check, don't fix.** Auto-fixing environments is risky and platform-specific; a precise `fix:` hint is safer.
- **A hand-written Redis protocol instead of a client library.** Two commands don't justify a dependency, and it's a good way to learn RESP.
- **psycopg is optional.** A plain TCP fallback keeps the base install light but only proves the port is open, so the result is a `warn`, not a `pass`.
- **`--ci` treats warnings as failures**, because in CI nobody reads warnings.

## Limitations
- Linux and macOS only. Windows isn't supported or tested.
- No TLS for Redis (`rediss://` gives a warning). HTTP health checks aren't built in yet.
- `init` heuristics only know Postgres and Redis images.

## Roadmap
- HTTP service type (`GET /health` expecting 200)
- Adopting it as `make doctor` in the Growth portfolio repos (spec milestone M5)
- `--fix` for trivial cases (copying `.env.example` to `.env`)

## Contributing
See [CONTRIBUTING.md](CONTRIBUTING.md). Licence: MIT.
