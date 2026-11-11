"""Record a run, and replay it to check it reproduces exactly.

Recording runs the agent live with both seams in record mode. Replay runs
the same adapter with both seams serving from the tape: tracefork checks
every model request's hash and every tool frame, the step order must match
the record, and the checker must reach the same verdict.
"""

from dataclasses import dataclass

import httpx2
from pydantic import BaseModel
from pydantic_ai.exceptions import AgentRunError
from pydantic_ai.settings import ModelSettings
from tracefork import Tape
from tracefork.nondet import find_divergence
from tracefork.redact import Redactor

from afr.agents import AgentAdapter
from afr.agents.contract import RunOutcome, Seams
from afr.runs import RunRecord, new_run_id, package_versions
from afr.seams.model import StepLoggingTransport, TapeMode, model_transport, openai_model
from afr.seams.secrets import build_redactor, strip_text
from afr.seams.steps import StepLog

DEFAULT_MODEL_URL = "http://127.0.0.1:11434/v1"  # Ollama's OpenAI-compatible endpoint
DEFAULT_MODEL = "qwen3.5:4b"
MAX_PROBLEM_CHARS = 300


@dataclass(frozen=True)
class ModelConfig:
    name: str = DEFAULT_MODEL
    base_url: str = DEFAULT_MODEL_URL
    # For tests: a fake model server in place of the network for live calls.
    live_transport: httpx2.MockTransport | None = None


class ReplayResult(BaseModel):
    """Whether a replay reproduced its recording, and if not, where it went wrong."""

    bit_exact: bool
    model_exchanges: int
    tool_frames: int
    same_steps: bool
    same_outcome: bool
    divergence: str | None = None


async def run_live(adapter: AgentAdapter, task_id: str, seams: Seams) -> RunOutcome:
    """Run a task with live calls; an error from the model is that run failing.

    A local model sometimes answers with output its server can't parse (Ollama
    returns HTTP 500 on a malformed tool call). That run didn't succeed, so it
    counts as failed, with the error as its problem, instead of ending a long
    batch. Only PydanticAI's run errors are caught: a divergence from a pinned
    prefix is tracefork's own `DivergenceError` and still stops everything,
    since it means the agent no longer reproduces its tape.
    """
    try:
        return await adapter.run(task_id, seams)
    except AgentRunError as error:
        problem = f"model error: {type(error).__name__}: {error}"[:MAX_PROBLEM_CHARS]
        return RunOutcome(failed=True, problems=[problem], final_answer="", tool_calls_logged=0)


def build_seams(
    tape: Tape, mode: TapeMode, config: ModelConfig, settings: ModelSettings
) -> tuple[Seams, StepLoggingTransport]:
    steps = StepLog()
    redactor = build_redactor()
    transport = model_transport(tape, mode, steps, redactor, live=config.live_transport)
    model = openai_model(config.name, config.base_url, transport, settings)
    return Seams(tape=tape, mode=mode, steps=steps, redactor=redactor, model=model), transport


async def record_run(
    adapter: AgentAdapter, task_id: str, config: ModelConfig
) -> tuple[RunRecord, Tape]:
    tape = Tape(agent_name=adapter.name)
    seams, _ = build_seams(tape, "record", config, adapter.model_settings)
    outcome = stripped(await run_live(adapter, task_id, seams), seams.redactor)
    afr_version, tracefork_version = package_versions()
    record = RunRecord(
        run_id=new_run_id(adapter.name, task_id),
        agent=adapter.name,
        agent_version=adapter.version,
        task_id=task_id,
        model=config.name,
        steps=seams.steps.steps,
        outcome=outcome,
        tape_digest=tape.digest(),
        afr_version=afr_version,
        tracefork_version=tracefork_version,
    )
    return record, tape


async def replay_run(adapter: AgentAdapter, record: RunRecord, tape: Tape) -> ReplayResult:
    config = ModelConfig(name=record.model)
    seams, transport = build_seams(tape, "replay", config, adapter.model_settings)
    try:
        outcome = await adapter.run(record.task_id, seams)
    except Exception as error:
        divergence = find_divergence(error)
        if divergence is None:
            raise
        return failed_replay(tape, str(divergence))
    all_served = transport.fully_consumed() and all(
        t.frames_fully_consumed() for t in seams.toolsets
    )
    same_steps = seams.steps.steps == record.steps
    same_outcome = outcome.same_verdict(record.outcome)
    return ReplayResult(
        bit_exact=all_served and same_steps and tape.digest() == record.tape_digest,
        model_exchanges=len(tape.exchanges),
        tool_frames=len(tape.tool_exchanges),
        same_steps=same_steps,
        same_outcome=same_outcome,
        divergence=None if all_served else "the replay ended before using every taped exchange",
    )


def stripped(outcome: RunOutcome, redactor: Redactor) -> RunOutcome:
    """The outcome with secrets stripped, as the replayed agent will see them (T1)."""
    return RunOutcome(
        failed=outcome.failed,
        problems=[strip_text(redactor, problem) for problem in outcome.problems],
        final_answer=strip_text(redactor, outcome.final_answer),
        tool_calls_logged=outcome.tool_calls_logged,
        tool_verdicts=outcome.tool_verdicts,
    )


def failed_replay(tape: Tape, divergence: str) -> ReplayResult:
    return ReplayResult(
        bit_exact=False,
        model_exchanges=len(tape.exchanges),
        tool_frames=len(tape.tool_exchanges),
        same_steps=False,
        same_outcome=False,
        divergence=divergence,
    )


def outcome_summary(outcome: RunOutcome) -> str:
    return "FAILED: " + "; ".join(outcome.problems) if outcome.failed else "passed"
