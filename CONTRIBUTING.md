# Contributing

1. `uv sync --all-extras`, `docker compose up -d --wait`, then `make check`.
2. A new tool needs a `ToolSpec` in `versions.py` **and** a real `--version` output line in `tests/test_versions.py`.
3. A new service type is a `ServiceCheck` subclass. Built-ins go in `checks/services.py`; third-party ones register under the
   `envcheck.services` entry-point group.
4. Never put a secret value in a message or fix hint. Tests check this for env vars and DSNs.
5. Use conventional commits.
