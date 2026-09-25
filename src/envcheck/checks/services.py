"""Network services: plain TCP, Redis (RESP PING, no dependency), Postgres (``SELECT 1``).

"Port open" and "service healthy" are different things: TCP only proves something is listening.
The Redis and Postgres checks speak the protocol and run a real command.
"""

from __future__ import annotations

import asyncio
import importlib.util
from urllib.parse import unquote, urlparse

from envcheck.checks.base import Check
from envcheck.config import ServiceSpec
from envcheck.context import Context
from envcheck.result import CheckResult

DEFAULT_PORTS = {"postgres": 5432, "postgresql": 5432, "redis": 6379}


class ServiceCheck(Check):
    kind = "services"
    service_type = "tcp"

    def __init__(self, name: str, spec: ServiceSpec) -> None:
        super().__init__(f"service:{name}")
        self.name, self.spec = name, spec
        self.timeout_s = spec.timeout_s + 1

    def target_url(self, ctx: Context) -> tuple[str | None, str | None]:
        """Return ``(url, error)``. The URL may come from an env var; its value is never printed."""
        env_name = self.spec.url_env or self.spec.dsn_env
        if env_name:
            value = ctx.env.get(env_name)
            if not value:
                return None, f"{env_name} is not set"
            return value, None
        return self.spec.url, None

    def host_port(self, ctx: Context) -> tuple[str, int] | str:
        url, error = self.target_url(ctx)
        if error:
            return error
        if url:
            parsed = urlparse(url)
            port = parsed.port or DEFAULT_PORTS.get(parsed.scheme.split("+")[0], 0)
            return parsed.hostname or "localhost", port
        assert self.spec.host is not None and self.spec.port is not None
        return self.spec.host, self.spec.port

    async def connect(self, host: str, port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        return await asyncio.wait_for(asyncio.open_connection(host, port), self.spec.timeout_s)

    async def run(self, ctx: Context) -> CheckResult:
        target = self.host_port(ctx)
        if isinstance(target, str):
            return self.result("fail", target, "set it in your .env")
        host, port = target
        try:
            _, writer = await self.connect(host, port)
        except (OSError, TimeoutError) as exc:
            return self.result(
                "fail",
                f"cannot connect to {host}:{port} ({type(exc).__name__})",
                "start the service (e.g. `docker compose up -d`)",
            )
        writer.close()
        await writer.wait_closed()
        return self.result("pass", f"{host}:{port} accepts TCP connections")


def _resp_command(*parts: str) -> bytes:
    out = [f"*{len(parts)}\r\n".encode()]
    for part in parts:
        data = part.encode()
        out.append(b"$%d\r\n%s\r\n" % (len(data), data))
    return b"".join(out)


class RedisCheck(ServiceCheck):
    service_type = "redis"

    async def run(self, ctx: Context) -> CheckResult:
        url, error = self.target_url(ctx)
        if error:
            return self.result("fail", error, "set it in your .env")
        parsed = urlparse(url) if url else None
        if parsed is not None and parsed.scheme == "rediss":
            return self.result("warn", "TLS (rediss://) is not supported yet; skipped the PING")
        target = self.host_port(ctx)
        assert not isinstance(target, str)
        host, port = target
        try:
            reader, writer = await self.connect(host, port)
        except (OSError, TimeoutError) as exc:
            return self.result(
                "fail",
                f"cannot connect to Redis at {host}:{port} ({type(exc).__name__})",
                "start Redis (e.g. `docker compose up -d redis`)",
            )
        try:
            if parsed is not None and parsed.password:
                user = unquote(parsed.username) if parsed.username else None
                auth = (
                    ("AUTH", user, unquote(parsed.password)) if user else ("AUTH", unquote(parsed.password))
                )
                writer.write(_resp_command(*auth))
                reply = await asyncio.wait_for(reader.readline(), self.spec.timeout_s)
                if not reply.startswith(b"+OK"):
                    return self.result(
                        "fail", "Redis rejected the credentials", "check the password in the URL"
                    )
            writer.write(_resp_command("PING"))
            reply = await asyncio.wait_for(reader.readline(), self.spec.timeout_s)
        except (OSError, TimeoutError) as exc:
            return self.result("fail", f"Redis did not answer PING ({type(exc).__name__})")
        finally:
            writer.close()
            await writer.wait_closed()
        if reply.startswith(b"+PONG"):
            return self.result("pass", f"Redis at {host}:{port} answered PONG")
        if reply.startswith(b"-NOAUTH"):
            return self.result(
                "fail", "Redis requires a password", "put it in the URL: redis://:password@host:port"
            )
        return self.result("fail", f"unexpected Redis reply {reply[:40]!r}")


class PostgresCheck(ServiceCheck):
    service_type = "postgres"

    async def run(self, ctx: Context) -> CheckResult:
        url, error = self.target_url(ctx)
        if error:
            return self.result("fail", error, "set it in your .env")
        if importlib.util.find_spec("psycopg") is None or url is None:
            tcp = await super().run(ctx)
            if tcp.status != "pass":
                return tcp
            hint = "install `envcheck[postgres]` to run SELECT 1" if url else "use a DSN to run SELECT 1"
            return self.result("warn", f"{tcp.message}; did not log in", hint)
        import psycopg

        dsn = url.replace("postgresql+asyncpg://", "postgresql://").replace(
            "postgres+psycopg://", "postgresql://"
        )
        try:
            conn = await psycopg.AsyncConnection.connect(
                dsn, connect_timeout=max(1, int(self.spec.timeout_s))
            )
            async with conn:
                cur = await conn.execute("SELECT 1")
                row = await cur.fetchone()
                version = conn.info.server_version
        except psycopg.OperationalError as exc:
            first_line = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
            # psycopg messages mention host/port/user but not the password
            return self.result(
                "fail",
                f"Postgres connection failed: {first_line}",
                "check the DSN and that Postgres is running",
            )
        if row != (1,):
            return self.result("fail", "Postgres answered SELECT 1 unexpectedly")
        major = version // 10000
        return self.result("pass", f"Postgres {major} accepted a login and answered SELECT 1")
