# envcheck: learning guide

A small codebase that touches a lot of backend fundamentals: async I/O, subprocesses, TCP, a wire protocol,
config validation, plugin systems and CI integration. Read it in this order.

## 1. The big idea
`envcheck.yaml` declares what a project needs. `plan()` turns it into a list of `Check` objects. The runner executes them
**concurrently** with timeouts, and a reporter prints the results. Every failure carries a `fix:` hint. Nothing is ever changed on the machine.

## 2. File tour (reading order)
| # | File | What to learn |
|---|---|---|
| 1 | `src/envcheck/result.py` | A tiny immutable result type (`frozen=True` dataclass). |
| 2 | `src/envcheck/config.py` | Strict pydantic schemas (`extra="forbid"`), cross-field validation (`model_validator`), versioned config. |
| 3 | `src/envcheck/versions.py` | Parsing messy CLI output with regexes, and translating `^`/`~` into `packaging` specifiers. |
| 4 | `src/envcheck/context.py` | Merging `.env` with the environment; `asyncio.create_subprocess_exec` with a timeout and kill. |
| 5 | `src/envcheck/checks/base.py` | An abstract base class with `ClassVar` metadata. |
| 6 | `src/envcheck/checks/system.py` | Tool, Docker, port and file checks; binding a socket to test a port. |
| 7 | `src/envcheck/checks/env.py` | Checking secrets without revealing them. |
| 8 | `src/envcheck/checks/services.py` | TCP connect vs. real health; **hand-written Redis RESP**; Postgres via psycopg. |
| 9 | `src/envcheck/checks/__init__.py` | The registry, plus **entry-point plugins** (`importlib.metadata.entry_points`). |
| 10 | `src/envcheck/runner.py` | `asyncio.gather`, `Semaphore`, `wait_for`, and turning exceptions into results. |
| 11 | `src/envcheck/reporters.py` | Rich tables, JSON, and JUnit XML with `xml.etree`. |
| 12 | `src/envcheck/init.py`, `cli.py` | Heuristic detection that reports what it guessed; a Typer callback plus subcommands. |

## 3. Key concepts, with pointers

### Concurrency for I/O-bound work (`runner.py`)
Each check mostly waits (for a subprocess, a socket or a database). `asyncio.gather` starts them all and waits for them
together, so the total time is roughly the slowest check, not the sum (`test_checks_run_concurrently`). A `Semaphore(16)` caps how many run at
once. `asyncio.wait_for(check.run(ctx), timeout)` cancels a check that hangs. **Why not threads?** You could use threads,
but asyncio makes timeouts and cancellation explicit and cheap, and the network APIs are already async.

### Subprocesses done safely (`context.run_command`)
- `create_subprocess_exec(*argv)` takes a **list** and never goes through a shell, so there's no injection risk.
- `stderr=STDOUT` merges the two streams, because some tools (`java -version`) print their version to stderr.
- On timeout, the process is **killed and reaped** (`proc.kill(); await proc.wait()`); otherwise you'd leak zombie processes.
- `FileNotFoundError` means "not installed" and becomes a clean `fail` with an install hint.

### "Port open" is not "service healthy" (`services.py`)
A TCP connect only proves something is listening. It could be the wrong service, or one that's half started. The Redis check
speaks the protocol: RESP encodes a command as an array of bulk strings, `*1\r\n$4\r\nPING\r\n`, and the healthy reply is
`+PONG\r\n`. With a password it sends `AUTH` first and expects `+OK`. The Postgres check logs in and runs `SELECT 1`. This is
the same distinction as Kubernetes liveness probes versus readiness probes.

### Testing network code without real services
`tests/test_checks.py` starts real asyncio TCP servers on port 0 (the OS picks a free port) that reply with fixed bytes. That's
enough to test TCP, `+PONG` and `-NOAUTH`. Real Postgres and Redis are only needed in the small `integration`-marked set.

### Testing a port is free (`PortFreeCheck`)
Try to `bind()` the port, then close the socket. `SO_REUSEADDR` stops leftover `TIME_WAIT` connections from causing false alarms, but
binding still fails if something is actively listening (`EADDRINUSE`). `EACCES` means a privileged port (below 1024 without root).

### Never leak secrets
Env checks report `X is set` or `does not match /pattern/`, never the value. Service URLs come from env vars and only the
host and port are printed. Tests assert that the password string doesn't appear anywhere in the output.

### Plugin systems with entry points
A third-party package declares `[project.entry-points."envcheck.services"] mongo = "pkg:MongoCheck"`.
`entry_points(group="envcheck.services")` discovers it at runtime, with no configuration and no imports of unknown modules until they're used.
pytest plugins and many CLI tools work the same way.

### Config design
`extra="forbid"` turns a typo (`servics:`) into an error instead of a silently ignored key. `version: 1` leaves room to
change the format later. A `model_validator` enforces "url, env var, or host + port" across fields.

### Exit codes and CI
`0` ready, `1` problems, `2` bad config. CI systems act on exit codes. JUnit XML is the lingua franca for "test results" tabs
(GitHub checks, GitLab and Jenkins all read it). `--ci` makes warnings fail, because nobody reads CI warnings.

## 4. Interview questions (with short answers)
1. **How do you run many I/O checks concurrently with timeouts?** `asyncio.gather` over coroutines, each wrapped in
   `asyncio.wait_for`, with a semaphore to bound concurrency.
2. **asyncio vs threads vs processes?** asyncio for I/O-bound work with many waits, threads for blocking libraries, and processes for CPU-bound
   work (the GIL).
3. **What happens to a subprocess when you time out?** Nothing, unless you kill it. Kill it and `wait()` to reap it, or it keeps running and turns into a
   zombie when it exits.
4. **Why avoid `shell=True`?** Shell injection, quoting bugs and platform differences. Pass an argv list instead.
5. **How do you check that a service is healthy, not just up?** Speak its protocol and run a trivial command (`PING`, `SELECT 1`), like
   a readiness probe.
6. **Explain the Redis protocol briefly.** RESP is text framing: `*N` arrays, `$len` bulk strings, `+` simple strings, `-` errors, `:` integers,
   and `\r\n` terminators.
7. **How do you test network code without real servers?** Start throwaway local servers on port 0 that return scripted bytes, and keep a
   small integration suite against real services.
8. **What is `SO_REUSEADDR`?** It lets you bind a port that still has connections in `TIME_WAIT`. It doesn't let two sockets listen on the same port
   (that's `SO_REUSEPORT`).
9. **How do you design a plugin system in Python?** Define a base class or protocol for plugins, and discover implementations through package entry points.
10. **How do you keep secrets out of logs?** Never format the value, log only presence or validity, parse URLs and print host and port only, and
    test for leaks.
11. **Why a strict config schema?** Typos fail loudly, and a versioned schema lets you evolve the format safely.
12. **Why is an unhandled exception inside one check a `fail` and not a crash?** One buggy check shouldn't hide the other results. The runner
    isolates failures.
13. **What does JUnit XML give you in CI?** Per-check pass/fail/skip, shown natively in CI test tabs, with history.
14. **How do you parse versions from arbitrary tools?** Tool-specific regexes with a generic `X.Y.Z` fallback, then
    `packaging.version.Version` for correct comparison (`1.10 > 1.9`).
15. **What does `^20` mean and how did you implement it?** "Compatible with 20": `>=20, <21`. It's translated to a PEP 440 `SpecifierSet`.
16. **Why does `init` print what it detected?** Heuristics are sometimes wrong, and silent guesses are worse than visible ones.

## 5. Try it yourself
- Add an `http` service type: `GET` a URL and expect a status code, with a timeout.
- Support `rediss://` using `asyncio.open_connection(..., ssl=True)`.
- Add a `--fix` flag that only does safe things, like copying `.env.example` to `.env`.
