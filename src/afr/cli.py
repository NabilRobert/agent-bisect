"""The `afr` command: one Typer app; each slice adds its own subcommands.

Commands stay thin: they parse options and call a function in the package,
so every behaviour is tested without going through the CLI.
"""

import asyncio
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(no_args_is_help=True, help="Find the step that broke an agent run.")
bench_app = typer.Typer(no_args_is_help=True, help="The planted-fault benchmark set.")
app.add_typer(bench_app, name="bench")

RUNS_DIR = Path("runs")
RunsDirOption = Annotated[Path, typer.Option(help="where runs are kept (git-ignored)")]
GatewayOption = Annotated[
    bool,
    typer.Option(
        "--gateway", help="record a1's tool calls through mcp-gateway ($AFR_GATEWAY_COMMAND)"
    ),
]


@app.command("versions")
def show_versions() -> None:
    """Print agent-bisect's and tracefork's versions (both go in every run record)."""
    typer.echo(f"agent-bisect {version('agent-bisect')}")
    typer.echo(f"tracefork {version('tracefork')}")


@app.command("record")
def record(
    agent: Annotated[str, typer.Argument(help="the agent, e.g. a1")],
    task: Annotated[str, typer.Option(help="the task id")],
    runs_dir: RunsDirOption = RUNS_DIR,
    gateway: GatewayOption = False,
) -> None:
    """Run one task live, taping every model and tool call."""
    from afr.agents import get_adapter, then_close
    from afr.recording import ModelConfig, outcome_summary, record_run
    from afr.runs import save_run

    adapter = get_adapter(agent, via_gateway=gateway)
    record_, tape = asyncio.run(then_close(adapter, record_run(adapter, task, ModelConfig())))
    run_dir = save_run(runs_dir, record_, tape)
    typer.echo(f"{run_dir}: {len(record_.steps)} steps, {outcome_summary(record_.outcome)}")


@app.command("replay")
def replay(run_dir: Annotated[Path, typer.Argument(help="a run folder under runs/")]) -> None:
    """Replay a recorded run with no network; exit 1 unless it reproduces exactly."""
    from afr.agents import get_adapter, then_close
    from afr.recording import replay_run
    from afr.runs import load_run

    record_, tape = load_run(run_dir)
    adapter = get_adapter(record_.agent)
    result = asyncio.run(then_close(adapter, replay_run(adapter, record_, tape)))
    typer.echo(result.model_dump_json(indent=2))
    if not (result.bit_exact and result.same_outcome):
        raise typer.Exit(1)


@app.command("replay-holds")
def replay_holds(
    agent: Annotated[str, typer.Argument(help="the agent, e.g. a1")],
    runs: Annotated[int, typer.Option(help="how many live runs to record and replay")] = 50,
    ollama_log: Annotated[
        Path | None, typer.Option(help="Ollama's server log, to count model calls independently")
    ] = None,
    runs_dir: RunsDirOption = RUNS_DIR,
    gateway: GatewayOption = False,
) -> None:
    """Record live runs, replay each offline, and check nothing was missed at the seams."""
    from afr.agents import get_adapter, then_close
    from afr.replay_holds import check_replay_holds

    adapter = get_adapter(agent, via_gateway=gateway)
    work = check_replay_holds(adapter, runs, runs_dir, ollama_log)
    report = asyncio.run(then_close(adapter, work))
    typer.echo(report.model_dump_json(indent=2))


@bench_app.command("build")
def bench_build(  # noqa: PLR0913 - each option bounds the build
    agent: Annotated[str, typer.Argument(help="the agent, e.g. a1")],
    set_name: Annotated[str, typer.Option("--set", help="dev (while writing methods) or frozen")],
    tasks: Annotated[str, typer.Option(help="comma-separated task ids; all by default")] = "",
    max_tasks: Annotated[int, typer.Option(help="tasks to plant faults in, of those kept")] = 3,
    samples: Annotated[int, typer.Option(help="continuations per probe")] = 5,
    out: Annotated[Path, typer.Option(help="where sets are written")] = Path("bench"),
    gateway: GatewayOption = False,
) -> None:
    """Filter tasks, plant faults, probe them and freeze the set (live: needs the model)."""
    from afr.agents import get_adapter, then_close
    from afr.bench.build import build_set
    from afr.bench.frozen import freeze
    from afr.recording import ModelConfig

    folder = out / set_name / agent
    if folder.exists():
        raise typer.BadParameter(f"{folder} exists; a built set is never rebuilt in place")
    adapter = get_adapter(agent, via_gateway=gateway)
    task_ids = tasks.split(",") if tasks else adapter.task_ids()
    work = build_set(adapter, task_ids, max_tasks, samples, ModelConfig(), typer.echo)
    built, runs = asyncio.run(then_close(adapter, work))
    frozen = freeze(folder, built, runs)
    effective = [plan.fault_id for plan, _ in frozen.effective_plans()]
    typer.echo(f"{folder}: {len(effective)} of {len(frozen.plans)} faults effective")
    typer.echo(f"fingerprint {frozen.fingerprint}")
