"""HTTP health checks: ``GET`` a URL and check the status code (and optionally the body).

Like the Redis check this speaks the protocol directly, with no HTTP client dependency. It sends one
HTTP/1.0 request with ``Connection: close``, so the server replies without chunked encoding and
closes the socket when the body ends. Redirects are **not** followed; a 3xx is reported as-is, since
a health endpoint that redirects is usually misconfigured.
"""

from __future__ import annotations

import asyncio
import contextlib
import ssl
from dataclasses import dataclass
from urllib.parse import urlparse

from envcheck.checks.services import ServiceCheck
from envcheck.context import Context
from envcheck.result import CheckResult

MAX_BODY = 64 * 1024  # enough for any health endpoint; bounds memory on a misbehaving server
MAX_HEADER_LINES = 100
USER_AGENT = "envcheck"


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes


class HttpProtocolError(Exception):
    """The server's reply wasn't valid HTTP."""


async def http_get(host: str, port: int, path: str, *, tls: bool, host_header: str) -> HttpResponse:
    """One ``GET``. The caller wraps it in ``asyncio.wait_for`` so the whole exchange has one deadline."""
    context = ssl.create_default_context() if tls else None
    reader, writer = await asyncio.open_connection(
        host, port, ssl=context, server_hostname=host if tls else None
    )
    try:
        request = (
            f"GET {path} HTTP/1.0\r\n"
            f"Host: {host_header}\r\n"
            f"User-Agent: {USER_AGENT}\r\n"
            "Accept: */*\r\n"
            "Connection: close\r\n\r\n"
        )
        writer.write(request.encode("ascii"))
        await writer.drain()

        status_line = await reader.readline()
        parts = status_line.decode("latin-1").split(" ", 2)
        if len(parts) < 2 or not parts[0].startswith("HTTP/") or not parts[1].isdigit():
            raise HttpProtocolError(f"bad status line {status_line[:40]!r}")
        status = int(parts[1])

        length: int | None = None
        for _ in range(MAX_HEADER_LINES):
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            name, _, value = line.decode("latin-1").partition(":")
            if name.strip().lower() == "content-length" and value.strip().isdigit():
                length = int(value.strip())
        else:
            raise HttpProtocolError("too many response headers")

        want = MAX_BODY if length is None else min(length, MAX_BODY)
        body = b""
        while len(body) < want:
            chunk = await reader.read(want - len(body))
            if not chunk:
                break
            body += chunk
        return HttpResponse(status, body)
    finally:
        writer.close()
        with contextlib.suppress(OSError, ssl.SSLError):  # the server may already have hung up
            await writer.wait_closed()


class HttpCheck(ServiceCheck):
    service_type = "http"

    def _describe(self, host: str, port: int, path: str) -> str:
        # Never print the query string or credentials, and don't echo a URL that came from an env
        # var: health URLs sometimes carry tokens.
        env_name = self.spec.url_env or self.spec.dsn_env
        if env_name:
            return f"{host}:{port} (from {env_name})"
        return f"{host}:{port}{path}"

    async def run(self, ctx: Context) -> CheckResult:
        url, error = self.target_url(ctx)
        if error:
            return self.result("fail", error, "set it in your .env")
        if url is None:
            assert self.spec.host is not None and self.spec.port is not None
            url = f"http://{self.spec.host}:{self.spec.port}/"
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return self.result("fail", "not an http(s) URL", "use http://host:port/path")
        tls = parsed.scheme == "https"
        host = parsed.hostname
        port = parsed.port or (443 if tls else 80)
        path = parsed.path or "/"
        request_target = f"{path}?{parsed.query}" if parsed.query else path
        default_port = port == (443 if tls else 80)
        host_header = host if default_port else f"{host}:{port}"
        where = self._describe(host, port, path)

        try:
            response = await asyncio.wait_for(
                http_get(host, port, request_target, tls=tls, host_header=host_header),
                self.spec.timeout_s,
            )
        except TimeoutError:
            return self.result(
                "fail",
                f"{where} did not answer within {self.spec.timeout_s:g}s",
                "is the service up and healthy?",
            )
        except ssl.SSLError as exc:
            return self.result("fail", f"TLS error talking to {where} ({exc.reason or 'SSLError'})")
        except OSError as exc:
            return self.result(
                "fail",
                f"cannot connect to {where} ({type(exc).__name__})",
                "start the service (e.g. `docker compose up -d`)",
            )
        except HttpProtocolError as exc:
            return self.result("fail", f"{where} did not speak HTTP: {exc}")

        expected = self.spec.expect_status
        ok_status = response.status in expected if expected else 200 <= response.status < 300
        if not ok_status:
            want = ", ".join(map(str, expected)) if expected else "2xx"
            return self.result(
                "fail",
                f"{where} returned HTTP {response.status} (expected {want})",
                "check the service logs",
            )
        needle = self.spec.expect_body
        if needle is not None and needle.encode() not in response.body:
            return self.result(
                "fail",
                f"{where} returned HTTP {response.status} but the body lacks {needle!r}",
                "check the health endpoint's output",
            )
        suffix = f" and contains {needle!r}" if needle is not None else ""
        return self.result("pass", f"{where} returned HTTP {response.status}{suffix}")
