from __future__ import annotations

import asyncio
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from typer.testing import CliRunner

from envcheck.checks import plan
from envcheck.checks.base import Check
from envcheck.cli import app
from envcheck.config import ConfigError, parse_config
from envcheck.context import Context
from envcheck.init import detect
from envcheck.reporters import to_junit, to_table
from envcheck.result import CheckResult
from envcheck.runner import exit_code, run_checks

runner = CliRunner()


class Slow(Check):
    kind = "test"
    timeout_s = 0.2

    async def run(self, ctx: Context) -> CheckResult:
        await asyncio.sleep(5)
        return self.result("pass", "never")


class Boom(Check):
    kind = "test"

    async def run(self, ctx: Context) -> CheckResult:
        raise RuntimeError("bug")


class Quick(Check):
    kind = "test"

    async def run(self, ctx: Context) -> CheckResult:
        await asyncio.sleep(0.3)
        return self.result("pass", "ok")


async def test_timeouts_and_crashes_become_failures(tmp_path: Path) -> None:
    results = await run_checks([Slow("slow"), Boom("boom")], Context(root=tmp_path, environ={}))
    assert [r.status for r in results] == ["fail", "fail"]
    assert "timed out" in results[0].message and "RuntimeError" in results[1].message


async def test_checks_run_concurrently(tmp_path: Path) -> None:
    loop = asyncio.get_running_loop()
    start = loop.time()
    await run_checks([Quick(f"q{i}") for i in range(10)], Context(root=tmp_path, environ={}))
    assert loop.time() - start < 1.5  # 10 x 0.3 s sequentially would be 3 s


async def test_skip_by_kind_or_id(tmp_path: Path) -> None:
    results = await run_checks([Quick("a"), Quick("b")], Context(root=tmp_path, environ={}), skip=["b"])
    assert [r.status for r in results] == ["pass", "skip"]


def test_exit_code_strictness() -> None:
    warn = [CheckResult("x", "warn", "m")]
    assert exit_code(warn, strict=False) == 0 and exit_code(warn, strict=True) == 1
    assert exit_code([CheckResult("x", "fail", "m")], strict=False) == 1


def test_config_validation() -> None:
    with pytest.raises(ConfigError):
        parse_config({"version": 2})
    with pytest.raises(ConfigError):
        parse_config({"services": {"db": {"type": "postgres"}}})  # no target
    with pytest.raises(ConfigError):
        parse_config({"typo_key": 1})
    with pytest.raises(ValueError, match="unknown type"):
        plan(parse_config({"services": {"m": {"type": "mongo", "host": "h", "port": 1}}}))


def test_plan_order_and_ids() -> None:
    cfg = parse_config(
        {
            "tools": {"python": ">=3.12"},
            "docker_daemon": True,
            "services": {"db": {"type": "postgres", "dsn_env": "DATABASE_URL"}},
            "ports_free": [8000],
            "env": {"required": ["DATABASE_URL"], "patterns": {"DATABASE_URL": "^postgres"}, "drift": {}},
            "files": ["pyproject.toml"],
        }
    )
    assert [c.id for c in plan(cfg)] == [
        "tool:python",
        "docker:daemon",
        "service:db",
        "port:8000",
        "env:DATABASE_URL",
        "env:drift",
        "file:pyproject.toml",
    ]


def test_reporters() -> None:
    results = [
        CheckResult("tool:python", "pass", "Python 3.12", duration_ms=12),
        CheckResult("env:X", "fail", "X is not set", fix="add X"),
        CheckResult("port:8000", "skip", "skipped in CI mode"),
        CheckResult("env:drift", "warn", "extra keys"),
    ]
    suite = ET.fromstring(to_junit(results).split("?>", 1)[1])
    assert suite.attrib["tests"] == "4" and suite.attrib["failures"] == "1" and suite.attrib["skipped"] == "1"
    assert suite.find("testcase[@name='env:X']/failure") is not None
    table = to_table(results, color=False)
    assert "X is not set" in table and "1 pass, 1 warn, 1 fail, 1 skip" in table


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "envcheck.yaml"
    path.write_text(text)
    return path


def test_cli_pass_fail_and_formats(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("TOKEN=abc\n")
    ok = write(tmp_path, "tools: {python: '>=3'}\nenv: {required: [TOKEN]}\nfiles: [.env]\n")
    result = runner.invoke(app, ["--config", str(ok)])
    assert result.exit_code == 0, result.output
    data = json.loads(runner.invoke(app, ["--config", str(ok), "--format", "json"]).output)
    assert data["summary"] == {"pass": 3}
    bad = write(tmp_path, "env: {required: [NOPE_NOT_SET_1234]}\n")
    assert runner.invoke(app, ["--config", str(bad)]).exit_code == 1


def test_cli_ci_mode_skips_and_is_strict(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text("A=\n")
    (tmp_path / ".env").write_text("A=1\nEXTRA=2\n")
    cfg = write(tmp_path, "env: {drift: {}}\nports_free: [1]\nci: {skip: [ports_free]}\n")
    local = runner.invoke(app, ["--config", str(cfg)])
    ci = runner.invoke(app, ["--config", str(cfg), "--ci", "--format", "junit"])
    assert local.exit_code in (0, 1)  # port 1 needs root locally; only the drift warn matters in CI
    assert ci.exit_code == 1 and 'skipped message="skipped in CI mode"' in ci.output


def test_cli_bad_config(tmp_path: Path) -> None:
    assert runner.invoke(app, ["--config", str(tmp_path / "missing.yaml")]).exit_code == 2
    assert runner.invoke(app, ["--config", str(write(tmp_path, "version: 9\n"))]).exit_code == 2


def test_init_detects_project_files(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nrequires-python = ">=3.12"\n')
    (tmp_path / "uv.lock").write_text("")
    (tmp_path / "package.json").write_text('{"engines": {"node": "^20"}}')
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  db: {image: postgres:16, ports: ['55432:5432']}\n  cache: {image: redis:7-alpine}\n"
        "  app: {image: myapp}\n"
    )
    (tmp_path / ".env.example").write_text("DATABASE_URL=\nREDIS_URL=\n")
    config, notes = detect(tmp_path)
    assert config["tools"] == {
        "python": ">=3.12",
        "uv": "*",
        "node": "^20",
        "docker": "*",
        "docker compose": "*",
    }
    assert config["services"] == {
        "db": {"type": "postgres", "host": "localhost", "port": 55432},
        "cache": {"type": "redis", "host": "localhost", "port": 6379},
    }
    assert config["env"]["required"] == ["DATABASE_URL", "REDIS_URL"]
    assert len(notes) >= 5
    parse_config(config)  # the draft must itself be valid


def test_init_command_does_not_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "envcheck.yaml"
    assert runner.invoke(app, ["init", "--path", str(target)]).exit_code == 0
    assert runner.invoke(app, ["init", "--path", str(target)]).exit_code == 1
    assert runner.invoke(app, ["init", "--path", str(target), "--force"]).exit_code == 0


def test_list_checks() -> None:
    out = runner.invoke(app, ["list-checks"]).output
    assert "postgres" in out and "terraform" in out
