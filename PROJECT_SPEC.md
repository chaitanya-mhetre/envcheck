# envcheck
> Declare the dev environment a project needs in one file, then check it locally or in CI with one command.

## 1. Problem & why it exists
New contributors lose hours because Python is 3.10 instead of 3.12, Docker isn't running, Postgres isn't on 5432, port 8000 is already taken, or `DATABASE_URL` is missing. READMEs describe the requirements, but nothing checks them.

**Existing tools in this space:**
- **mise / asdf**: install and pin tool versions. They manage installation; they don't really validate services or environment variables.
- **devcontainers / Nix**: fully reproducible environments. Powerful, but heavyweight.
- **dotenv-linter**, **envalid** (Node), **pydantic-settings**: environment variable validation only.
- Project-specific `doctor` commands, e.g. `flutter doctor` and `brew doctor`, are the inspiration.

**Honest positioning:** it's a **learning project with a small practical niche**, a generic, declarative `doctor` command for any repo. It doesn't install anything. It checks and explains how to fix each problem. The niche is real but small. It's useful for Chaitanya's own portfolio repos (every project's `make doctor`).

## 2. What this proves to an employer
| Skill | Target requirement |
|---|---|
| Python CLI design, subprocess handling, cross-platform code | Python backend |
| Networking basics (ports, TCP connect, service health) | Backend / DevOps |
| CI integration, exit codes, machine-readable output | CI/CD |
| Plugin architecture | Software design |

## 3. Scope
### In scope (v1)
- A config file, `envcheck.yaml`, in the repo root.
- Check types:
  - tool present plus a version constraint (`python>=3.12`, `node^20`, `docker`, `docker compose`, `aws`, `terraform`, `uv`);
  - Docker daemon running;
  - service reachable (TCP host:port);
  - Postgres (connect plus `SELECT 1`) and Redis (`PING`);
  - port free;
  - environment variable present or matching a pattern, and `.env` vs `.env.example` drift;
  - file exists.
- Output: coloured table, JSON, JUnit XML (for CI); each failure comes with a `fix:` hint.
- Modes: `envcheck` (local) and `envcheck --ci` (skips interactive checks, strict exit code).
- Parallel checks with per-check timeouts.

### Out of scope (explicitly)
- Installing or fixing anything automatically (maybe later, `--fix` for trivial cases).
- Windows support in v1 (Linux and macOS only; documented).

## 4. Architecture
```
envcheck.yaml ─► config loader (pydantic schema, versioned) ─► check planner
                                                               │
                             registry of Check plugins ◄───────┘
               (ToolVersion, DockerDaemon, TcpService, Postgres, Redis, PortFree, EnvVar, EnvDrift, File)
                                                               │
                                async runner (concurrency, timeouts)
                                                               │
                                reporters: table | json | junit
```
- **Plugin registry:** each check type is isolated and testable, and third parties can add checks through entry points.
- **Async runner:** network checks are I/O bound; running them in parallel keeps `envcheck` under a couple of seconds.
- **Version parsing:** each tool prints its version differently. Each ToolVersion check has a regex and uses `packaging.version`.

## 5. Tech stack & justification
Python 3.12, Typer, pydantic, `asyncio` (subprocess plus open_connection), `packaging`, `rich` for tables, optional extras `psycopg` and `redis`. Shipped with `pipx`/`uvx` support so it runs without polluting the project venv.

## 6. Data model
```yaml
version: 1
tools:   { python: ">=3.12", uv: "*", docker: "*", node: ">=20" }
services:
  postgres: { type: postgres, dsn_env: DATABASE_URL }
  redis:    { type: redis, url_env: REDIS_URL }
ports_free: [8000]
env:
  required: [DATABASE_URL, REDIS_URL]
  drift_check: { example: .env.example, actual: .env }
ci: { skip: [ports_free] }
```
Result: `CheckResult { id, status: pass|warn|fail|skip, message, fix_hint, duration_ms }`.

## 7. API / interface design
```
envcheck                 # run all checks
envcheck --ci --format junit > envcheck.xml
envcheck init            # scaffold envcheck.yaml by detecting pyproject/package.json/docker-compose
envcheck list-checks
```

## 8. Key engineering problems
- Robust version extraction from arbitrary `--version` output, including tools that print to stderr.
- Timeouts and cancellation for hanging subprocesses and connections.
- Never printing secret values (show `DATABASE_URL=set`, not its value).
- `init` auto-detection heuristics that don't guess wrong silently (always print what was detected).

## 9. Milestones
- **M1: Config schema + tool/version checks + table output.** Accept when: unit tests cover ≥ 10 real version-string fixtures.
- **M2: Service checks (TCP, Postgres, Redis, Docker) + async runner.** Accept when: integration tests run against docker-compose services in CI.
- **M3: Env var + drift checks + JSON/JUnit + `--ci`.** Accept when: GitHub Actions shows JUnit results.
- **M4: `init` + plugin entry points + PyPI 0.1.0.**
- **M5: Adopt it in every Growth portfolio repo (`make doctor`).**

## 10. Testing strategy
Unit tests with fake subprocess outputs, integration tests with Postgres/Redis service containers, and snapshot tests for reporters.

## 11. Observability
`--verbose` shows each command run and its timing.

## 12. Security
- No shell=True.
- Secrets never printed.
- DSNs parsed but never echoed.

## 13. Deployment
PyPI, runnable with `uvx envcheck`.

## 14. Evaluation / measurements to collect
- Wall time for a typical config: TBD, measure.

## 15. Prerequisite learning
`learning/python-06-exceptions-errors`, `learning/python-08-async-concurrency`, `learning/python-10-packaging`, `learning/backend-01-http-networking`.

## 16. Interview talking points
- How do you run many I/O checks concurrently with timeouts?
- How do you design an extensible plugin system in Python (entry points)?
- How do you check that a TCP service is up vs that it's actually healthy?

## 17. Resume bullet templates
- "Built envcheck, a declarative environment-validation CLI (tools, services, ports, env vars) with async checks and JUnit output, used across [N] of my repositories' CI pipelines."

## 18. Open questions / uncertainties
- Is the name available on PyPI? Several `envcheck` packages likely exist, so check and rename if needed.
