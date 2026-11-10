"""Record a run, and replay it to check it reproduces exactly.

Recording runs the agent live with both seams in record mode. Replay runs
the same adapter with both seams serving from the tape: tracefork checks
every model request's hash and every tool frame, the step order must match
the record, and the checker must reach the same verdict.
"""

from dataclasses import dataclass

import httpx2
from pydantic import BaseModel
from tracefork import Tape
from tracefork.nondet import find_divergence

from afr.agents import AgentAdapter
from afr.agents.contract import RunOutcome, Seams
from afr.runs import RunRecord, new_run_id, package_versions
from afr.seams.model import StepLoggingTransport, TapeMode, model_transport, openai_model
from afr.seams.secrets import build_redactor, strip_text
from afr.seams.steps import StepLog

DEFAULT_MODEL_URL = "http://127.0.0.1:11434/v1"  # Ollama's OpenAI-compatible endpoint
DEFAULT_MODEL = "qwen3.5:4b"


@dataclass(frozen=True)
class ModelConfig:
    name: str = DEFAULT_MODEL
    base_url: str = DEFAULT_MODEL_URL
    # For tests: a fake model server in place of the network while recording.
    live_transport: httpx2.AsyncBaseTransport | None = None


class ReplayResult(BaseModel):
    """Whether a replay reproduced its recording, and if not, where it went wrong."""

    bit_exact: bool
    model_exchanges: int
    tool_frames: int
    same_steps: bool
    same_outcome: bool
    divergence: str | None = None


def build_seams(
    tape: Tape, mode: TapeMode, config: ModelConfig
) -> tuple[Seams, StepLoggingTransport]:
    steps = StepLog()
    redactor = build_redactor()
    transport = model_transport(tape, mode, steps, redactor, live=config.live_transport)
    model = openai_model(config.name, config.base_url, transport)
    return Seams(tape=tape, mode=mode, steps=steps, redactor=redactor, model=model), transport


async def record_run(
    adapter: AgentAdapter, task_id: str, config: ModelConfig
) -> tuple[RunRecord, Tape]:
    tape = Tape(agent_name=adapter.name)
    seams, _ = build_seams(tape, "record", config)
    outcome = stripped(await adapter.run(task_id, seams), seams)
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
    seams, transport = build_seams(tape, "replay", ModelConfig(name=record.model))
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
    same_outcome = outcome == record.outcome
    return ReplayResult(
        bit_exact=all_served and same_steps and tape.digest() == record.tape_digest,
        model_exchanges=len(tape.exchanges),
        tool_frames=len(tape.tool_exchanges),
        same_steps=same_steps,
        same_outcome=same_outcome,
        divergence=None if all_served else "the replay ended before using every taped exchange",
    )


def stripped(outcome: RunOutcome, seams: Seams) -> RunOutcome:
    """The outcome with secrets stripped, as the replayed agent will see them (T1)."""
    return RunOutcome(
        failed=outcome.failed,
        problems=[strip_text(seams.redactor, problem) for problem in outcome.problems],
        final_answer=strip_text(seams.redactor, outcome.final_answer),
        tool_calls_logged=outcome.tool_calls_logged,
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
