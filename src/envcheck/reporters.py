"""Table (for humans), JSON (for tools), JUnit XML (for CI test tabs)."""

from __future__ import annotations

import io
import json
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict

from rich.console import Console
from rich.table import Table

from envcheck.result import CheckResult

STYLE = {"pass": "green", "warn": "yellow", "fail": "red", "skip": "dim"}
SYMBOL = {"pass": "✔", "warn": "!", "fail": "✘", "skip": "-"}


def summary(results: Sequence[CheckResult]) -> str:
    counts = Counter(r.status for r in results)
    return ", ".join(f"{counts.get(s, 0)} {s}" for s in ("pass", "warn", "fail", "skip"))


def to_table(results: Sequence[CheckResult], color: bool = True) -> str:
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("")
    table.add_column("check")
    table.add_column("result")
    table.add_column("fix")
    for r in results:
        style = STYLE[r.status]
        table.add_row(f"[{style}]{SYMBOL[r.status]}[/]", r.id, f"[{style}]{r.message}[/]", r.fix or "")
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=color, no_color=not color, width=140)
    console.print(table)
    console.print(summary(results))
    return buf.getvalue()


def to_json(results: Sequence[CheckResult]) -> str:
    return json.dumps(
        {"summary": dict(Counter(r.status for r in results)), "results": [asdict(r) for r in results]},
        indent=2,
    )


def to_junit(results: Sequence[CheckResult]) -> str:
    counts = Counter(r.status for r in results)
    suite = ET.Element(
        "testsuite",
        name="envcheck",
        tests=str(len(results)),
        failures=str(counts.get("fail", 0)),
        skipped=str(counts.get("skip", 0)),
        time=f"{sum(r.duration_ms for r in results) / 1000:.3f}",
    )
    for r in results:
        case = ET.SubElement(
            suite, "testcase", classname="envcheck", name=r.id, time=f"{r.duration_ms / 1000:.3f}"
        )
        detail = r.message + (f"\nfix: {r.fix}" if r.fix else "")
        if r.status == "fail":
            ET.SubElement(case, "failure", message=r.message).text = detail
        elif r.status == "skip":
            ET.SubElement(case, "skipped", message=r.message)
        elif r.status == "warn":
            ET.SubElement(case, "system-out").text = f"WARNING: {detail}"
    return ET.tostring(suite, encoding="unicode", xml_declaration=True)
