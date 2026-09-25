from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest

import envcheck.checks.system as system
from envcheck.checks.env import EnvDriftCheck, EnvVarCheck
from envcheck.checks.services import PostgresCheck, RedisCheck, ServiceCheck
from envcheck.checks.system import DockerDaemonCheck, FileCheck, PortFreeCheck, ToolCheck
from envcheck.config import ServiceSpec
from envcheck.context import CommandNotFoundError, Context, parse_dotenv


def ctx(tmp_path: Path, env: dict[str, str] | None = None, dotenv: str | None = None) -> Context:
    if dotenv is not None:
        (tmp_path / ".env").write_text(dotenv)
    return Context(root=tmp_path, environ=env or {})


def fake_command(code: int = 0, output: str = "", missing: bool = False) -> Callable[..., object]:
    async def run(argv: tuple[str, ...], timeout_s: float, context: object = None) -> tuple[int, str]:
        if missing:
            raise CommandNotFoundError(argv[0])
        return code, output

    return run


# ---- tools / docker ----------------------------------------------------------------------------


async def test_tool_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "run_command", fake_command(output="Python 3.12.3"))
    r = await ToolCheck("python", ">=3.12").run(ctx(tmp_path))
    assert r.status == "pass" and "3.12.3" in r.message


async def test_tool_too_old(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "run_command", fake_command(output="v18.19.0"))
    r = await ToolCheck("node", "^20").run(ctx(tmp_path))
    assert r.status == "fail" and r.fix


async def test_tool_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "run_command", fake_command(missing=True))
    r = await ToolCheck("terraform", "*").run(ctx(tmp_path))
    assert r.status == "fail" and "not found" in r.message


async def test_tool_unreadable_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "run_command", fake_command(output="weird"))
    assert (await ToolCheck("thing", ">=1").run(ctx(tmp_path))).status == "warn"
    assert (await ToolCheck("thing", "*").run(ctx(tmp_path))).status == "pass"


async def test_real_python_on_this_machine(tmp_path: Path) -> None:
    r = await ToolCheck("python", ">=3").run(ctx(tmp_path))
    assert r.status == "pass"


async def test_docker_daemon_permission_hint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        system, "run_command", fake_command(code=1, output="permission denied while trying to connect")
    )
    r = await DockerDaemonCheck().run(ctx(tmp_path))
    assert r.status == "fail" and r.fix is not None and "docker group" in r.fix


# ---- ports / files -----------------------------------------------------------------------------


async def test_port_in_use_and_free(tmp_path: Path) -> None:
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        r = await PortFreeCheck(port).run(ctx(tmp_path))
        assert r.status == "fail" and "lsof" in (r.fix or "")
    assert (await PortFreeCheck(port).run(ctx(tmp_path))).status == "pass"


async def test_file_check(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x")
    assert (await FileCheck("a.txt").run(ctx(tmp_path))).status == "pass"
    assert (await FileCheck("b.txt").run(ctx(tmp_path))).status == "fail"


# ---- env -----------------------------------------------------------------------------------------


def test_parse_dotenv() -> None:
    text = "A=1\nexport B=\"two words\"\n# comment\nC=3 # trailing\nD=\nE='q'\nnot a line\n"
    assert parse_dotenv(text) == {"A": "1", "B": "two words", "C": "3", "D": "", "E": "q"}


async def test_env_var_never_prints_value(tmp_path: Path) -> None:
    secret = "postgresql://u:hunter2@db/app"
    c = ctx(tmp_path, env={"DATABASE_URL": secret})
    ok = await EnvVarCheck("DATABASE_URL", r"^postgres").run(c)
    bad = await EnvVarCheck("DATABASE_URL", r"^mysql").run(c)
    assert ok.status == "pass" and bad.status == "fail"
    assert all("hunter2" not in (r.message + (r.fix or "")) for r in (ok, bad))


async def test_env_from_dotenv_and_environment_wins(tmp_path: Path) -> None:
    c = ctx(tmp_path, env={"A": "from-env"}, dotenv="A=from-file\nB=file-only\n")
    assert c.env == {"A": "from-env", "B": "file-only"}
    assert (await EnvVarCheck("B").run(c)).status == "pass"
    assert (await EnvVarCheck("MISSING").run(c)).status == "fail"


async def test_empty_env_var_warns(tmp_path: Path) -> None:
    assert (await EnvVarCheck("X").run(ctx(tmp_path, env={"X": ""}))).status == "warn"


async def test_drift(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text("A=\nB=\n")
    check = EnvDriftCheck(".env.example", ".env")
    assert (await check.run(ctx(tmp_path))).status == "fail"  # .env missing
    (tmp_path / ".env").write_text("A=1\n")
    r = await check.run(ctx(tmp_path))
    assert r.status == "fail" and "B" in r.message
    (tmp_path / ".env").write_text("A=1\nB=2\nC=3\n")
    assert (await check.run(ctx(tmp_path))).status == "warn"
    (tmp_path / ".env").write_text("A=1\nB=2\n")
    assert (await check.run(ctx(tmp_path))).status == "pass"


# ---- services against local fake servers --------------------------------------------------------


@pytest.fixture
async def fake_server() -> AsyncIterator[Callable[[bytes], object]]:
    servers: list[asyncio.Server] = []

    async def start(reply: bytes) -> int:
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                await reader.read(1024)
                writer.write(reply)
                await writer.drain()
            finally:
                writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        servers.append(server)
        return int(server.sockets[0].getsockname()[1])

    yield start
    for s in servers:
        s.close()
        await s.wait_closed()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def test_tcp_up_and_down(tmp_path: Path, fake_server: Callable[[bytes], object]) -> None:
    port = await fake_server(b"")  # type: ignore[misc]
    up = ServiceSpec(type="tcp", host="127.0.0.1", port=port)
    assert (await ServiceCheck("api", up).run(ctx(tmp_path))).status == "pass"
    down = ServiceSpec(type="tcp", host="127.0.0.1", port=free_port(), timeout_s=1)
    r = await ServiceCheck("api", down).run(ctx(tmp_path))
    assert r.status == "fail" and "docker compose" in (r.fix or "")


async def test_redis_pong_and_noauth(tmp_path: Path, fake_server: Callable[[bytes], object]) -> None:
    pong = await fake_server(b"+PONG\r\n")  # type: ignore[misc]
    noauth = await fake_server(b"-NOAUTH Authentication required.\r\n")  # type: ignore[misc]
    ok = await RedisCheck("cache", ServiceSpec(type="redis", url=f"redis://127.0.0.1:{pong}/0")).run(
        ctx(tmp_path)
    )
    assert ok.status == "pass"
    r = await RedisCheck("cache", ServiceSpec(type="redis", url=f"redis://127.0.0.1:{noauth}")).run(
        ctx(tmp_path)
    )
    assert r.status == "fail" and "password" in r.message


async def test_service_url_from_missing_env(tmp_path: Path) -> None:
    r = await RedisCheck("cache", ServiceSpec(type="redis", url_env="REDIS_URL")).run(ctx(tmp_path))
    assert r.status == "fail" and r.message == "REDIS_URL is not set"


async def test_postgres_down(tmp_path: Path) -> None:
    spec = ServiceSpec(type="postgres", url=f"postgresql://u:secret@127.0.0.1:{free_port()}/db", timeout_s=1)
    r = await PostgresCheck("db", spec).run(ctx(tmp_path))
    assert r.status == "fail" and "secret" not in r.message
