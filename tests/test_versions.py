from __future__ import annotations

import pytest
from packaging.version import Version

from envcheck.versions import extract_version, satisfies, to_specifier

# Real `--version` outputs, copied from the tools (one per line of the tuple).
FIXTURES = [
    ("python", "Python 3.12.14\n", "3.12.14"),
    ("uv", "uv 0.12.6 (x86_64-unknown-linux-gnu)\n", "0.12.6"),
    ("node", "v20.11.1\n", "20.11.1"),
    ("docker", "Docker version 29.6.2, build dfc4efb\n", "29.6.2"),
    ("docker compose", "Docker Compose version v2.29.1\n", "2.29.1"),
    ("git", "git version 2.43.0\n", "2.43.0"),
    ("go", "go version go1.22.5 linux/amd64\n", "1.22.5"),
    (
        "java",
        'openjdk version "21.0.2" 2024-01-16\nOpenJDK Runtime Environment (build 21.0.2+13-58)\n',
        "21.0.2",
    ),
    ("aws", "aws-cli/2.15.30 Python/3.11.8 Linux/6.5.0 exe/x86_64.ubuntu.22\n", "2.15.30"),
    ("terraform", "Terraform v1.9.5\non linux_amd64\n", "1.9.5"),
    (
        "kubectl",
        "Client Version: v1.30.3\nKustomize Version: v5.0.4-0.20230601165947-6ce0bf390ce3\n",
        "1.30.3",
    ),
    ("psql", "psql (PostgreSQL) 16.4 (Ubuntu 16.4-0ubuntu0.24.04.2)\n", "16.4"),
    ("redis-cli", "redis-cli 7.2.5\n", "7.2.5"),
    ("make", "GNU Make 4.3\nBuilt for x86_64-pc-linux-gnu\n", "4.3"),
    ("gh", "gh version 2.55.0 (2024-08-20)\nhttps://github.com/cli/cli/releases/tag/v2.55.0\n", "2.55.0"),
    ("some-unknown-tool", "sometool release 3.4.1-beta\n", "3.4.1"),
]


@pytest.mark.parametrize(("tool", "output", "expected"), FIXTURES, ids=[f[0] for f in FIXTURES])
def test_extract_version(tool: str, output: str, expected: str) -> None:
    assert extract_version(tool, output) == Version(expected)


def test_no_version_in_output() -> None:
    assert extract_version("node", "command not recognised") is None


@pytest.mark.parametrize(
    ("version", "constraint", "ok"),
    [
        ("3.12.1", ">=3.12", True),
        ("3.11.9", ">=3.12", False),
        ("20.11.1", "^20", True),
        ("21.0.0", "^20", False),
        ("1.9.5", "~1.9", True),
        ("1.10.0", "~1.9", False),
        ("2.29.1", "*", True),
        ("3.12.4", "3.12", True),  # bare "3.12" means any 3.12.x
        ("3.13.0", "3.12", False),
        ("1.2.3", ">=1.0,<2", True),
    ],
)
def test_constraints(version: str, constraint: str, ok: bool) -> None:
    assert satisfies(Version(version), constraint) is ok


def test_invalid_constraint() -> None:
    with pytest.raises(ValueError):
        to_specifier(">>3")
