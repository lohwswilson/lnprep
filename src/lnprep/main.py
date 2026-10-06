"""
lnprep - Standalone Lecture Notes Preparation CLI.
Follows the architecture standard of /opt/cstation:
Python >= 3.13, Typer >= 0.16.0, Rich >= 14.1.0, hatchling build backend.
"""

from __future__ import annotations

import click
import typer
from rich import print as rprint

from lnprep import __version__
from lnprep.commands.audit import audit_command
from lnprep.commands.brief import brief_command
from lnprep.commands.cache import app as cache_app
from lnprep.commands.check import check_command
from lnprep.commands.cross_check import cross_check_command
from lnprep.commands.enhance import enhance_command
from lnprep.commands.extract import extract_command
from lnprep.commands.generate import generate_command
from lnprep.commands.init import init_command
from lnprep.commands.sync import sync_command
from lnprep.commands.verify import verify_command
from lnprep.commands.write import write_command
from lnprep.config import config


def version_callback(value: bool) -> None:
    if value:
        rprint(f"[bold cyan]lnprep[/bold cyan] version [bold green]{__version__}[/bold green]")
        raise typer.Exit()


app = typer.Typer(
    name="lnprep",
    help="Lecture Notes Preparation CLI - 3-Zone Notes, Direct XML Injection, SBC Audit & Citations",
    no_args_is_help=True,
)

# Register subcommands
app.command(name="init")(init_command)
app.command(name="extract")(extract_command)
app.command(name="generate")(generate_command)
app.command(name="enhance")(enhance_command)
app.command(name="audit")(audit_command)
app.command(name="verify")(verify_command)
app.command(name="write")(write_command)
app.add_typer(cache_app, name="cache")
app.command(name="cross-check")(cross_check_command)
app.command(name="sync")(sync_command)
app.command(name="brief")(brief_command)
app.command(name="check")(check_command)


@app.callback()
def main_callback(
    ctx: typer.Context,
    version: bool = typer.Option(
        None,
        "--version",
        "-V",
        callback=version_callback,
        is_eager=True,
        help="Show lnprep version and exit",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output and tracebacks",
    ),
) -> None:
    """Lecture Notes Preparation CLI"""
    config.verbose = verbose


def main() -> None:
    """Main CLI entrypoint."""
    try:
        app()
    except (typer.Exit, click.Abort):
        raise
    except Exception as e:
        if config.verbose:
            raise
        rprint(f"[red]✘[/red] {e}")
        raise typer.Exit(1)


if __name__ == "__main__":
    main()
