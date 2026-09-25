"""Run checks concurrently, each with its own timeout. A crashing check becomes a ``fail``."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from dataclasses import replace

from envcheck.checks.base import Check
from envcheck.context import Context
from envcheck.result import CheckResult

MAX_CONCURRENCY = 16


async def _run_one(check: Check, ctx: Context, sem: asyncio.Semaphore) -> CheckResult:
    async with sem:
        start = time.perf_counter()
        try:
            result = await asyncio.wait_for(check.run(ctx), check.timeout_s)
        except TimeoutError:
            result = check.result("fail", f"timed out after {check.timeout_s:.0f}s")
        except Exception as exc:  # a buggy check must not take the whole run down
            result = check.result("fail", f"check crashed: {type(exc).__name__}: {exc}")
        return replace(result, duration_ms=int((time.perf_counter() - start) * 1000))


async def run_checks(checks: Sequence[Check], ctx: Context, skip: Sequence[str] = ()) -> list[CheckResult]:
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    skipped = set(skip)

    async def run(check: Check) -> CheckResult:
        if check.id in skipped or check.kind in skipped:
            return check.result("skip", "skipped in CI mode")
        return await _run_one(check, ctx, sem)

    return list(await asyncio.gather(*(run(c) for c in checks)))


def exit_code(results: Sequence[CheckResult], strict: bool) -> int:
    bad = {"fail", "warn"} if strict else {"fail"}
    return 1 if any(r.status in bad for r in results) else 0
