"""
Output formatting and console utilities for lnprep CLI.
Supports human-readable Rich console rendering and machine-readable JSON.
"""

from __future__ import annotations

import json
import sys
from enum import Enum
from typing import Any, Callable, Optional

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# Shared Rich console instances
console = Console()
err_console = Console(stderr=True)


class OutputFormat(str, Enum):
    TABLE = "table"
    JSON = "json"


def print_json(data: Any, indent: int = 2) -> None:
    """Print formatted JSON to stdout for machine consumption."""
    sys.stdout.write(json.dumps(data, indent=indent, default=str) + "\n")
    sys.stdout.flush()


def print_success(message: str) -> None:
    """Print a green success message."""
    console.print(f"[bold green]✔[/bold green] {message}")


def print_warning(message: str) -> None:
    """Print a yellow warning message to stderr."""
    err_console.print(f"[bold yellow]⚠️ [/bold yellow] {message}")


def print_error(message: str) -> None:
    """Print a red error message to stderr."""
    err_console.print(f"[bold red]✘[/bold red] {message}")


def print_info(message: str) -> None:
    """Print a cyan informational message."""
    console.print(f"[cyan]ℹ[/cyan] {message}")


def print_header(title: str, subtitle: Optional[str] = None) -> None:
    """Print a styled section header panel."""
    text = Text(title, style="bold cyan")
    if subtitle:
        text.append(f"\n{subtitle}", style="dim")
    console.print(Panel(text, expand=False, border_style="cyan"))


def print_formatted(
    data: Any,
    as_json: bool = False,
    table_renderer: Optional[Callable[[], None]] = None,
) -> None:
    """
    Print data according to selected output mode.
    If as_json is True, dumps json.
    Otherwise runs table_renderer if provided, or pretty-prints to console.
    """
    if as_json:
        print_json(data)
    elif table_renderer is not None:
        table_renderer()
    else:
        console.print(data)
