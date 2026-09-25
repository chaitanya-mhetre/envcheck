"""HTTP health check against a local asyncio HTTP server (no network, no extra dependencies)."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from envcheck.checks import plan
from envcheck.checks.http import MAX_BODY, HttpCheck
from envcheck.config import Config, ServiceSpec
from envcheck.context import Context


def ctx(tmp_path: Path, env: dict[str, str] | None = None) -> Context:
    return Context(root=tmp_path, environ=env or {})


@dataclass
class Reply:
    status: int = 200
    body: bytes = b"ok"
    delay_s: float = 0.0
    raw: bytes | None = None  # send these bytes verbatim instead of a well-formed response
    content_length: bool = True


@dataclass
class Server:
    port: int
    requests: list[bytes] = field(default_factory=list)


StartServer = Callable[[Reply], Awaitable[Server]]


@pytest.fixture
async def http_server() -> AsyncIterator[StartServer]:
    servers: list[asyncio.Server] = []

    async def start(reply: Reply) -> Server:
        info = Server(port=0)

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                info.requests.append(await reader.readuntil(b"\r\n\r\n"))
                await asyncio.sleep(reply.delay_s)
                if reply.raw is not None:
                    writer.write(reply.raw)
                else:
                    head = f"HTTP/1.1 {reply.status} X\r\n"
                    if reply.content_length:
                        head += f"Content-Length: {len(reply.body)}\r\n"
                    writer.write(head.encode() + b"\r\n" + reply.body)
                await writer.drain()
            except (asyncio.IncompleteReadError, ConnectionError):
                pass
            finally:
                writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        servers.append(server)
        info.port = int(server.sockets[0].getsockname()[1])
        return info

    yield start
    for s in servers:
        s.close()
        await s.wait_closed()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def check(tmp_path: Path, env: dict[str, str] | None = None, **spec: object) -> tuple[str, str]:
    result = await HttpCheck("web", ServiceSpec(type="http", **spec)).run(ctx(tmp_path, env))  # type: ignore[arg-type]
    return result.status, result.message


async def test_2xx_passes_by_default(tmp_path: Path, http_server: StartServer) -> None:
    srv = await http_server(Reply(status=204, body=b""))
    status, message = await check(tmp_path, url=f"http://127.0.0.1:{srv.port}/health")
    assert status == "pass" and "HTTP 204" in message


async def test_non_2xx_fails_by_default(tmp_path: Path, http_server: StartServer) -> None:
    srv = await http_server(Reply(status=503, body=b"down"))
    status, message = await check(tmp_path, url=f"http://127.0.0.1:{srv.port}/health")
    assert status == "fail" and "HTTP 503 (expected 2xx)" in message


async def test_expected_status_list(tmp_path: Path, http_server: StartServer) -> None:
    srv = await http_server(Reply(status=401))
    url = f"http://127.0.0.1:{srv.port}/admin"
    assert (await check(tmp_path, url=url, expect_status=[200, 401]))[0] == "pass"
    status, message = await check(tmp_path, url=url, expect_status=200)
    assert status == "fail" and "expected 200" in message


async def test_redirect_is_not_followed(tmp_path: Path, http_server: StartServer) -> None:
    srv = await http_server(Reply(status=302, body=b""))
    status, message = await check(tmp_path, url=f"http://127.0.0.1:{srv.port}/")
    assert status == "fail" and "HTTP 302" in message


async def test_body_substring(tmp_path: Path, http_server: StartServer) -> None:
    srv = await http_server(Reply(body=b'{"status": "ok", "db": "up"}'))
    url = f"http://127.0.0.1:{srv.port}/health"
    status, message = await check(tmp_path, url=url, expect_body='"db": "up"')
    assert status == "pass" and "contains" in message
    status, message = await check(tmp_path, url=url, expect_body="redis")
    assert status == "fail" and "lacks 'redis'" in message


async def test_body_without_content_length_reads_until_close(
    tmp_path: Path, http_server: StartServer
) -> None:
    srv = await http_server(Reply(body=b"x" * 5000 + b"READY", content_length=False))
    status, _ = await check(tmp_path, url=f"http://127.0.0.1:{srv.port}/", expect_body="READY")
    assert status == "pass"


async def test_body_read_is_bounded(tmp_path: Path, http_server: StartServer) -> None:
    # The marker sits past MAX_BODY, so it must not be found: memory stays bounded.
    srv = await http_server(Reply(body=b"x" * (MAX_BODY + 10) + b"MARK", content_length=False))
    status, _ = await check(tmp_path, url=f"http://127.0.0.1:{srv.port}/", expect_body="MARK")
    assert status == "fail"


async def test_timeout(tmp_path: Path, http_server: StartServer) -> None:
    srv = await http_server(Reply(delay_s=2))
    status, message = await check(tmp_path, url=f"http://127.0.0.1:{srv.port}/", timeout_s=0.3)
    assert status == "fail" and "did not answer within 0.3s" in message


async def test_connection_refused(tmp_path: Path) -> None:
    status, message = await check(tmp_path, url=f"http://127.0.0.1:{free_port()}/", timeout_s=1)
    assert status == "fail" and "cannot connect" in message


async def test_not_http(tmp_path: Path, http_server: StartServer) -> None:
    srv = await http_server(Reply(raw=b"+PONG\r\n"))  # e.g. pointed at Redis by mistake
    status, message = await check(tmp_path, url=f"http://127.0.0.1:{srv.port}/")
    assert status == "fail" and "did not speak HTTP" in message


async def test_request_line_and_host_header(tmp_path: Path, http_server: StartServer) -> None:
    srv = await http_server(Reply())
    await check(tmp_path, url=f"http://127.0.0.1:{srv.port}/health?deep=1")
    request = srv.requests[0].decode()
    assert request.startswith("GET /health?deep=1 HTTP/1.0\r\n")
    assert f"Host: 127.0.0.1:{srv.port}\r\n" in request


async def test_host_and_port_without_url(tmp_path: Path, http_server: StartServer) -> None:
    srv = await http_server(Reply())
    assert (await check(tmp_path, host="127.0.0.1", port=srv.port))[0] == "pass"


async def test_url_from_env_is_never_printed(tmp_path: Path, http_server: StartServer) -> None:
    srv = await http_server(Reply(status=500))
    env = {"HEALTH_URL": f"http://127.0.0.1:{srv.port}/health?token=s3cret"}
    status, message = await check(tmp_path, env=env, url_env="HEALTH_URL")
    assert status == "fail" and "s3cret" not in message and "from HEALTH_URL" in message
    status, message = await check(tmp_path, url_env="MISSING_URL")
    assert status == "fail" and message == "MISSING_URL is not set"


async def test_query_string_not_printed_for_config_url(tmp_path: Path, http_server: StartServer) -> None:
    srv = await http_server(Reply())
    _, message = await check(tmp_path, url=f"http://127.0.0.1:{srv.port}/h?key=abc")
    assert "key=abc" not in message and "/h" in message


async def test_rejects_non_http_url(tmp_path: Path) -> None:
    status, message = await check(tmp_path, url="ftp://example.com/")
    assert status == "fail" and "not an http(s) URL" in message


def test_config_validation() -> None:
    assert ServiceSpec(type="http", url="http://x/", expect_status=204).expect_status == [204]
    with pytest.raises(ValueError, match="only apply to type: http"):
        ServiceSpec(type="redis", url="redis://x", expect_body="PONG")
    with pytest.raises(ValueError, match="between 100 and 599"):
        ServiceSpec(type="http", url="http://x/", expect_status=[700])


def test_http_type_is_registered() -> None:
    config = Config.model_validate(
        {"services": {"web": {"type": "http", "url": "http://localhost:8081/health"}}}
    )
    [only] = plan(config)
    assert isinstance(only, HttpCheck) and only.id == "service:web"
