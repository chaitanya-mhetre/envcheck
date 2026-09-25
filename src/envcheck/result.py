"""The outcome of one check."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Status = Literal["pass", "warn", "fail", "skip"]


@dataclass(frozen=True)
class CheckResult:
    id: str  # e.g. "tool:python", "service:postgres", "env:DATABASE_URL"
    status: Status
    message: str
    fix: str | None = None
    duration_ms: int = 0
