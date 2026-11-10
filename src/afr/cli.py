"""The `afr` command: one Typer app; each slice adds its own subcommands.

Commands stay thin: they parse options and call a function in the package,
so every behaviour is tested without going through the CLI.
"""

from importlib.metadata import version

import typer

app = typer.Typer(no_args_is_help=True, help="Find the step that broke an agent run.")


@app.command("versions")
def show_versions() -> None:
    """Print agent-bisect's and tracefork's versions (both go in every run record)."""
    typer.echo(f"agent-bisect {version('agent-bisect')}")
    typer.echo(f"tracefork {version('tracefork')}")


@app.callback()
def main() -> None:
    """Keep `afr versions` a subcommand while it is the only one."""
