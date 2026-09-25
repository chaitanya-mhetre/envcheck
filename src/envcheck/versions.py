"""Finding a tool's version and checking it against a constraint.

Every tool prints its version differently (and ``java`` prints to stderr), so each known tool
has its own command and regex. Unknown tools fall back to ``<tool> --version`` and the first
``X.Y[.Z]`` in the output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

GENERIC = re.compile(r"(\d+\.\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class ToolSpec:
    argv: tuple[str, ...]
    pattern: re.Pattern[str] = GENERIC
    fix: str | None = None


TOOLS: dict[str, ToolSpec] = {
    "python": ToolSpec(
        ("python3", "--version"),
        re.compile(r"Python (\d+\.\d+\.\d+)"),
        "install with `uv python install` or your OS package manager",
    ),
    "uv": ToolSpec(
        ("uv", "--version"),
        re.compile(r"uv (\d+\.\d+\.\d+)"),
        "curl -LsSf https://astral.sh/uv/install.sh | sh",
    ),
    "node": ToolSpec(("node", "--version"), re.compile(r"v(\d+\.\d+\.\d+)"), "install via nvm or fnm"),
    "npm": ToolSpec(("npm", "--version")),
    "docker": ToolSpec(
        ("docker", "--version"),
        re.compile(r"Docker version (\d+\.\d+\.\d+)"),
        "install Docker Engine or Docker Desktop",
    ),
    "docker compose": ToolSpec(
        ("docker", "compose", "version"),
        re.compile(r"Docker Compose version v?(\d+\.\d+\.\d+)"),
        "install the Docker Compose v2 plugin",
    ),
    "git": ToolSpec(("git", "--version"), re.compile(r"git version (\d+\.\d+\.\d+)")),
    "go": ToolSpec(("go", "version"), re.compile(r"go version go(\d+\.\d+(?:\.\d+)?)")),
    "java": ToolSpec(("java", "-version"), re.compile(r'version "(\d+(?:\.\d+){0,2})')),
    "aws": ToolSpec(("aws", "--version"), re.compile(r"aws-cli/(\d+\.\d+\.\d+)")),
    "terraform": ToolSpec(("terraform", "version"), re.compile(r"Terraform v(\d+\.\d+\.\d+)")),
    "kubectl": ToolSpec(("kubectl", "version", "--client"), re.compile(r"Client Version: v(\d+\.\d+\.\d+)")),
    "psql": ToolSpec(("psql", "--version"), re.compile(r"psql \(PostgreSQL\) (\d+(?:\.\d+)?)")),
    "redis-cli": ToolSpec(("redis-cli", "--version"), re.compile(r"redis-cli (\d+\.\d+\.\d+)")),
    "make": ToolSpec(("make", "--version"), re.compile(r"GNU Make (\d+\.\d+(?:\.\d+)?)")),
    "gh": ToolSpec(("gh", "--version"), re.compile(r"gh version (\d+\.\d+\.\d+)")),
    "flutter": ToolSpec(("flutter", "--version"), re.compile(r"Flutter (\d+\.\d+\.\d+)")),
}


def tool_spec(name: str) -> ToolSpec:
    return TOOLS.get(name, ToolSpec((name, "--version")))


def extract_version(name: str, output: str) -> Version | None:
    match = tool_spec(name).pattern.search(output) or GENERIC.search(output)
    if match is None:
        return None
    try:
        return Version(match.group(1))
    except InvalidVersion:
        return None


def to_specifier(constraint: str) -> SpecifierSet:
    """Accept PEP 440 specifiers plus npm-style ``^`` and ``~`` and ``*``.

    ``^20`` -> ``>=20,<21``; ``^1.4`` -> ``>=1.4,<2``; ``~1.4`` -> ``>=1.4,<1.5``.
    """
    c = constraint.strip()
    if c in ("", "*"):
        return SpecifierSet()
    if c[0] in "^~":
        base = Version(c[1:])
        major, minor = base.release[0], (base.release[1] if len(base.release) > 1 else 0)
        upper = f"{major + 1}" if c[0] == "^" else f"{major}.{minor + 1}"
        return SpecifierSet(f">={base},<{upper}")
    if c[0].isdigit():
        c = f"=={c}.*" if c.count(".") < 2 else f"=={c}"
    try:
        return SpecifierSet(c)
    except InvalidSpecifier as exc:
        raise ValueError(f"invalid version constraint {constraint!r}") from exc


def satisfies(version: Version, constraint: str) -> bool:
    return to_specifier(constraint).contains(version, prereleases=True)
