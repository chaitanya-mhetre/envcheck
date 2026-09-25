"""``envcheck``, ``envcheck init``, ``envcheck list-checks``."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Annotated, Literal

import typer

from envcheck.checks import plan, service_types
from envcheck.config import DEFAULT_FILE, ConfigError, load_config
from envcheck.context import Context
from envcheck.init import detect, render
from envcheck.reporters import to_json, to_junit, to_table
from envcheck.runner import exit_code, run_checks
from envcheck.versions import TOOLS

app = typer.Typer(help="Check that a machine has what this project needs.", invoke_without_command=True)

Format = Literal["table", "json", "junit"]


@app.callback()
def main(
    ctx: typer.Context,
    config: Annotated[Path, typer.Option("--config", "-c", help="config file")] = Path(DEFAULT_FILE),
    ci: Annotated[bool, typer.Option("--ci", help="CI mode: apply ci.skip, warnings fail (strict)")] = False,
    fmt: Annotated[Format, typer.Option("--format", "-f")] = "table",
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="print each command run")] = False,
) -> None:
    """Run every check in envcheck.yaml. Exit 0 = ready, 1 = problems, 2 = bad config."""
    if ctx.invoked_subcommand is not None:
        return
    if verbose:
        logging.basicConfig(level=logging.INFO, format="envcheck: %(message)s")
    try:
        cfg = load_config(config)
        checks = plan(cfg)
    except (ConfigError, ValueError) as exc:
        typer.echo(f"envcheck: {exc}", err=True)
        raise typer.Exit(2) from exc
    context = Context(root=config.resolve().parent, dotenv=cfg.env.dotenv, verbose=verbose)
    results = asyncio.run(run_checks(checks, context, skip=cfg.ci.skip if ci else ()))
    if fmt == "json":
        typer.echo(to_json(results))
    elif fmt == "junit":
        typer.echo(to_junit(results))
    else:
        typer.echo(to_table(results, color=not ci), nl=False)
    raise typer.Exit(exit_code(results, strict=ci and cfg.ci.strict))


@app.command()
def init(
    path: Annotated[Path, typer.Option("--path", help="where to write")] = Path(DEFAULT_FILE),
    force: Annotated[bool, typer.Option("--force", help="overwrite an existing file")] = False,
) -> None:
    """Draft envcheck.yaml from pyproject.toml, package.json, docker-compose and .env.example."""
    if path.exists() and not force:
        typer.echo(f"{path} already exists (use --force to overwrite)", err=True)
        raise typer.Exit(1)
    config, notes = detect(path.resolve().parent)
    for note in notes or ["nothing detected; wrote a minimal file"]:
        typer.echo(f"detected: {note}")
    path.write_text(render(config), encoding="utf-8")
    typer.echo(f"wrote {path}")


@app.command("list-checks")
def list_checks() -> None:
    """Show the check kinds, service types and tools with built-in version parsing."""
    typer.echo("kinds:    tools, docker_daemon, services, ports_free, env, files")
    typer.echo(f"services: {', '.join(sorted(service_types()))}")
    typer.echo(f"tools:    {', '.join(sorted(TOOLS))} (any other tool: `<tool> --version`)")
