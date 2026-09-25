"""Against real Postgres and Redis: `docker compose up -d` (ports 55438 / 56385)."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from envcheck.checks.services import PostgresCheck, RedisCheck
from envcheck.config import ServiceSpec
from envcheck.context import Context

PG_URL = "postgresql://envcheck:envcheck@127.0.0.1:55438/envcheck"
REDIS_URL = "redis://:envcheck-pass@127.0.0.1:56385/0"


def reachable(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (reachable(55438) and reachable(56385)),
        reason="Postgres/Redis not running; start them with `docker compose up -d`",
    ),
]


async def test_real_postgres_select_1(tmp_path: Path) -> None:
    r = await PostgresCheck("db", ServiceSpec(type="postgres", url=PG_URL)).run(
        Context(root=tmp_path, environ={})
    )
    assert r.status == "pass" and "SELECT 1" in r.message


async def test_real_postgres_bad_password(tmp_path: Path) -> None:
    url = PG_URL.replace("envcheck:envcheck@", "envcheck:wrong-pw@")
    r = await PostgresCheck("db", ServiceSpec(type="postgres", url=url)).run(
        Context(root=tmp_path, environ={})
    )
    assert r.status == "fail" and "wrong-pw" not in r.message


async def test_real_redis_with_auth(tmp_path: Path) -> None:
    ctx = Context(root=tmp_path, environ={"REDIS_URL": REDIS_URL})
    assert (await RedisCheck("c", ServiceSpec(type="redis", url_env="REDIS_URL")).run(ctx)).status == "pass"
    no_pw = ServiceSpec(type="redis", url="redis://127.0.0.1:56385/0")
    r = await RedisCheck("c", no_pw).run(ctx)
    assert r.status == "fail" and "password" in r.message
    bad = ServiceSpec(type="redis", url="redis://:nope@127.0.0.1:56385/0")
    assert (await RedisCheck("c", bad).run(ctx)).status == "fail"
