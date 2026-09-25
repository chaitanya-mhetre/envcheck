"""Check registry. Built-in service types plus any registered under the
``envcheck.services`` entry-point group:

    [project.entry-points."envcheck.services"]
    mongo = "mypkg.checks:MongoCheck"      # a ServiceCheck subclass
"""

from __future__ import annotations

from importlib.metadata import entry_points

from envcheck.checks.base import Check
from envcheck.checks.env import EnvDriftCheck, EnvVarCheck
from envcheck.checks.http import HttpCheck
from envcheck.checks.services import PostgresCheck, RedisCheck, ServiceCheck
from envcheck.checks.system import DockerDaemonCheck, FileCheck, PortFreeCheck, ToolCheck
from envcheck.config import Config

BUILTIN_SERVICES: dict[str, type[ServiceCheck]] = {
    "tcp": ServiceCheck,
    "redis": RedisCheck,
    "postgres": PostgresCheck,
    "postgresql": PostgresCheck,
    "http": HttpCheck,
    "https": HttpCheck,
}


def service_types() -> dict[str, type[ServiceCheck]]:
    types = dict(BUILTIN_SERVICES)
    for ep in entry_points(group="envcheck.services"):
        types[ep.name] = ep.load()
    return types


def plan(config: Config) -> list[Check]:
    """Turn a config into the list of checks to run, in a stable order."""
    checks: list[Check] = [ToolCheck(name, constraint) for name, constraint in config.tools.items()]
    if config.docker_daemon:
        checks.append(DockerDaemonCheck())
    types = service_types()
    for name, spec in config.services.items():
        if spec.type not in types:
            raise ValueError(
                f"service {name!r}: unknown type {spec.type!r} (known: {', '.join(sorted(types))})"
            )
        checks.append(types[spec.type](name, spec))
    checks += [PortFreeCheck(port) for port in config.ports_free]
    for var in dict.fromkeys([*config.env.required, *config.env.patterns]):
        checks.append(EnvVarCheck(var, config.env.patterns.get(var)))
    if config.env.drift is not None:
        checks.append(EnvDriftCheck(config.env.drift.example, config.env.drift.actual))
    checks += [FileCheck(path) for path in config.files]
    return checks


__all__ = ["Check", "plan", "service_types"]
