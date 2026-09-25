"""Shared state for a run: working directory, environment (with .env merged), verbosity."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("envcheck")


def parse_dotenv(text: str) -> dict[str, str]:
    """Minimal .env parser: ``KEY=value``, optional ``export``, quotes, ``#`` comments."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if key:
            values[key] = value
    return values


@dataclass
class Context:
    root: Path
    environ: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    dotenv: str | None = ".env"
    verbose: bool = False

    def __post_init__(self) -> None:
        merged: dict[str, str] = {}
        if self.dotenv:
            path = self.root / self.dotenv
            if path.is_file():
                merged.update(parse_dotenv(path.read_text(encoding="utf-8")))
        merged.update(self.environ)  # real environment wins over .env, like most loaders
        self.env: dict[str, str] = merged


class CommandNotFoundError(Exception):
    pass


async def run_command(argv: tuple[str, ...], timeout_s: float, ctx: Context | None = None) -> tuple[int, str]:
    """Run without a shell; return ``(returncode, stdout + stderr)``. Kills the process on timeout."""
    if ctx is not None and ctx.verbose:
        log.info("run: %s", " ".join(argv))
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
    except (FileNotFoundError, PermissionError) as exc:
        raise CommandNotFoundError(argv[0]) from exc
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout_s)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode or 0, out.decode("utf-8", "replace")
