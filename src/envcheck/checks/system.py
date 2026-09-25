"""Tools, the Docker daemon, free ports, files."""

from __future__ import annotations

import errno
import socket

from envcheck.checks.base import Check
from envcheck.context import CommandNotFoundError, Context, run_command
from envcheck.result import CheckResult
from envcheck.versions import extract_version, satisfies, to_specifier, tool_spec


class ToolCheck(Check):
    kind = "tools"

    def __init__(self, name: str, constraint: str) -> None:
        super().__init__(f"tool:{name}")
        self.name, self.constraint = name, constraint
        to_specifier(constraint)  # fail fast on a bad constraint

    async def run(self, ctx: Context) -> CheckResult:
        spec = tool_spec(self.name)
        try:
            code, output = await run_command(spec.argv, self.timeout_s, ctx)
        except CommandNotFoundError:
            return self.result("fail", f"{self.name} not found on PATH", spec.fix or f"install {self.name}")
        if code != 0:
            return self.result("fail", f"`{' '.join(spec.argv)}` exited with {code}", spec.fix)
        version = extract_version(self.name, output)
        if version is None:
            if self.constraint.strip() in ("", "*"):
                return self.result("pass", f"{self.name} present (version not detected)")
            return self.result("warn", f"could not read {self.name}'s version from its output")
        if satisfies(version, self.constraint):
            return self.result("pass", f"{self.name} {version} (wanted {self.constraint})")
        return self.result(
            "fail",
            f"{self.name} {version} does not satisfy {self.constraint}",
            spec.fix or f"install {self.name} {self.constraint}",
        )


class DockerDaemonCheck(Check):
    kind = "docker_daemon"

    def __init__(self) -> None:
        super().__init__("docker:daemon")

    async def run(self, ctx: Context) -> CheckResult:
        try:
            code, output = await run_command(
                ("docker", "info", "--format", "{{.ServerVersion}}"), self.timeout_s, ctx
            )
        except CommandNotFoundError:
            return self.result("fail", "docker CLI not found", "install Docker")
        if code == 0:
            return self.result("pass", f"Docker daemon running (server {output.strip()})")
        fix = "start Docker (`sudo systemctl start docker` or open Docker Desktop)"
        if "permission denied" in output.lower():
            fix = "add your user to the docker group: `sudo usermod -aG docker $USER`, then log in again"
        return self.result("fail", "Docker daemon not reachable", fix)


class PortFreeCheck(Check):
    kind = "ports_free"

    def __init__(self, port: int) -> None:
        super().__init__(f"port:{port}")
        self.port = port

    async def run(self, ctx: Context) -> CheckResult:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            # SO_REUSEADDR ignores leftover TIME_WAIT sockets but still fails if something listens.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("0.0.0.0", self.port))  # noqa: S104 - we only test the bind, then close
            except OSError as exc:
                if exc.errno == errno.EADDRINUSE:
                    return self.result(
                        "fail",
                        f"port {self.port} is already in use",
                        f"find the process: `lsof -i :{self.port}` (or `ss -ltnp | grep :{self.port}`)",
                    )
                if exc.errno == errno.EACCES:
                    return self.result("warn", f"no permission to bind port {self.port} (privileged port?)")
                raise
        return self.result("pass", f"port {self.port} is free")


class FileCheck(Check):
    kind = "files"

    def __init__(self, path: str) -> None:
        super().__init__(f"file:{path}")
        self.path = path

    async def run(self, ctx: Context) -> CheckResult:
        if (ctx.root / self.path).exists():
            return self.result("pass", f"{self.path} exists")
        return self.result("fail", f"{self.path} is missing", f"create {self.path}")
