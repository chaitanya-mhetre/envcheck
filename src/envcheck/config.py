"""The ``envcheck.yaml`` schema.

```yaml
version: 1
tools: {python: ">=3.12", uv: "*", docker: "*", node: "^20"}
docker_daemon: true
services:
  db:    {type: postgres, dsn_env: DATABASE_URL}
  cache: {type: redis, url: "redis://localhost:6379/0"}
  api:   {type: tcp, host: localhost, port: 8080}
  web:   {type: http, url: "http://localhost:8081/health", expect_status: 200, expect_body: ok}
ports_free: [8000]
env:
  required: [DATABASE_URL]
  patterns: {DATABASE_URL: "^postgres(ql)?://"}
  dotenv: .env                 # also read values from this file (default .env)
  drift: {example: .env.example, actual: .env}
files: [pyproject.toml]
ci: {skip: [ports_free]}       # check kinds or ids to skip with --ci
```
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

DEFAULT_FILE = "envcheck.yaml"


HTTP_TYPES = frozenset({"http", "https"})


class ConfigError(Exception):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ServiceSpec(_Strict):
    type: str  # built-in: tcp | postgres | redis; more via plugins
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    url: str | None = None  # redis://..., postgresql://...
    url_env: str | None = None
    dsn_env: str | None = None  # alias of url_env for postgres
    timeout_s: float = Field(default=3.0, gt=0)
    # http/https only: accepted status codes (default: any 2xx) and a substring the body must contain
    expect_status: list[int] | None = None
    expect_body: str | None = None

    @field_validator("expect_status", mode="before")
    @classmethod
    def _status_list(cls, value: Any) -> Any:
        return [value] if isinstance(value, int) else value

    @model_validator(mode="after")
    def _has_target(self) -> ServiceSpec:
        if not (self.url or self.url_env or self.dsn_env or (self.host and self.port)):
            raise ValueError("service needs url, url_env/dsn_env, or host + port")
        if self.type not in HTTP_TYPES and (self.expect_status or self.expect_body is not None):
            raise ValueError("expect_status/expect_body only apply to type: http")
        if self.expect_status and any(not 100 <= s <= 599 for s in self.expect_status):
            raise ValueError("expect_status codes must be between 100 and 599")
        return self


class DriftSpec(_Strict):
    example: str = ".env.example"
    actual: str = ".env"


class EnvSpec(_Strict):
    required: list[str] = Field(default_factory=list)
    patterns: dict[str, str] = Field(default_factory=dict)
    dotenv: str | None = ".env"
    drift: DriftSpec | None = None


class CISpec(_Strict):
    skip: list[str] = Field(default_factory=list)
    strict: bool = True  # in CI, warnings fail the run


class Config(_Strict):
    version: Literal[1] = 1
    tools: dict[str, str] = Field(default_factory=dict)
    docker_daemon: bool = False
    services: dict[str, ServiceSpec] = Field(default_factory=dict)
    ports_free: list[int] = Field(default_factory=list)
    env: EnvSpec = Field(default_factory=EnvSpec)
    files: list[str] = Field(default_factory=list)
    ci: CISpec = Field(default_factory=CISpec)


def parse_config(data: Any, source: str = DEFAULT_FILE) -> Config:
    try:
        return Config.model_validate(data or {})
    except ValidationError as exc:
        raise ConfigError(f"{source}: {exc}") from exc


def load_config(path: Path) -> Config:
    if not path.is_file():
        raise ConfigError(f"{path} not found (run `envcheck init` to create one)")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    return parse_config(data, str(path))
