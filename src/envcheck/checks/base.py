from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from envcheck.context import Context
from envcheck.result import CheckResult, Status


class Check(ABC):
    """One thing to verify. Subclasses set ``kind`` and implement :meth:`run`."""

    kind: ClassVar[str]
    timeout_s: float = 10.0

    def __init__(self, id: str) -> None:  # noqa: A002 - "id" is the natural name here
        self.id = id

    def result(self, status: Status, message: str, fix: str | None = None) -> CheckResult:
        return CheckResult(self.id, status, message, fix)

    @abstractmethod
    async def run(self, ctx: Context) -> CheckResult: ...
