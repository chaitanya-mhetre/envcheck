"""Environment variables. Values are **never** printed, only whether they are set / valid."""

from __future__ import annotations

import re

from envcheck.checks.base import Check
from envcheck.context import Context, parse_dotenv
from envcheck.result import CheckResult


class EnvVarCheck(Check):
    kind = "env"

    def __init__(self, name: str, pattern: str | None = None) -> None:
        super().__init__(f"env:{name}")
        self.name = name
        self.pattern = re.compile(pattern) if pattern else None

    async def run(self, ctx: Context) -> CheckResult:
        value = ctx.env.get(self.name)
        if value is None:
            return self.result(
                "fail", f"{self.name} is not set", f"add {self.name}=... to your .env (see .env.example)"
            )
        if value == "":
            return self.result("warn", f"{self.name} is set but empty")
        if self.pattern is not None and not self.pattern.search(value):
            return self.result(
                "fail",
                f"{self.name} is set but does not match /{self.pattern.pattern}/",
                f"check the format of {self.name}",
            )
        return self.result("pass", f"{self.name} is set")


class EnvDriftCheck(Check):
    kind = "env"

    def __init__(self, example: str, actual: str) -> None:
        super().__init__("env:drift")
        self.example, self.actual = example, actual

    async def run(self, ctx: Context) -> CheckResult:
        example_path, actual_path = ctx.root / self.example, ctx.root / self.actual
        if not example_path.is_file():
            return self.result("warn", f"{self.example} not found, cannot compare")
        if not actual_path.is_file():
            return self.result("fail", f"{self.actual} is missing", f"cp {self.example} {self.actual}")
        wanted = set(parse_dotenv(example_path.read_text(encoding="utf-8")))
        have = set(parse_dotenv(actual_path.read_text(encoding="utf-8")))
        missing, extra = sorted(wanted - have), sorted(have - wanted)
        if missing:
            return self.result(
                "fail",
                f"{self.actual} is missing keys from {self.example}: {', '.join(missing)}",
                f"add the missing keys to {self.actual}",
            )
        if extra:
            return self.result(
                "warn",
                f"{self.actual} has keys not in {self.example}: {', '.join(extra)}",
                f"document them in {self.example}",
            )
        return self.result("pass", f"{self.actual} matches {self.example} ({len(wanted)} keys)")
