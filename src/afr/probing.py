"""Probes: pin a run's first k steps, let the agent continue live, and count failures.

The measurement plan's primitive. A probe at `k` serves steps `0 … k-1` from
the run's tape (tracefork checks each pinned request still matches), then
the agent goes on live: fresh model samples, fresh tool calls, against a
sandbox only. Repeated `samples` times, the share of continuations the
checker fails is `f(k)`: `f(0)` is the task's base failure rate, and pinning
every step reproduces the run.
"""

import time
from dataclasses import dataclass, replace

from pydantic import BaseModel
from tracefork import Tape

from afr.agents import AgentAdapter
from afr.agents.contract import RunOutcome
from afr.recording import ModelConfig, build_seams
from afr.seams.steps import Step


@dataclass(frozen=True)
class PinnedRun:
    """What a probe needs of a run: its tape, its step order, and how to rerun it."""

    tape: Tape
    steps: list[Step]
    task_id: str
    model: str


class Continuation(BaseModel):
    """One live continuation after the pinned steps."""

    failed: bool
    live_model_calls: int
    live_tool_calls: int
    seconds: float


class ProbeResult(BaseModel):
    k: int
    continuations: list[Continuation]

    @property
    def failures(self) -> int:
        return sum(continuation.failed for continuation in self.continuations)

    @property
    def failure_rate(self) -> float:
        return self.failures / len(self.continuations)


def prefix_tape(run: PinnedRun, k: int) -> Tape:
    """A new tape holding exactly the run's first `k` steps."""
    pinned = run.steps[:k]
    model_steps = sum(step.kind == "model" for step in pinned)
    tool_frames = len(pinned) - model_steps  # tool calls and the tool listing share a list
    prefix = Tape(boundary=run.tape.boundary, agent_name=run.tape.agent_name)
    prefix.exchanges = list(run.tape.exchanges[:model_steps])
    prefix.tool_exchanges = list(run.tape.tool_exchanges[:tool_frames])
    return prefix


async def continue_from(
    adapter: AgentAdapter, run: PinnedRun, k: int, config: ModelConfig
) -> tuple[RunOutcome, Tape, list[Step]]:
    """Pin the first `k` steps and run the rest live once; returns the continuation's tape."""
    tape = prefix_tape(run, k)
    # The model name is in every request body, so the pinned ones must match the run's.
    seams, _ = build_seams(tape, "pin", replace(config, name=run.model), adapter.model_settings)
    outcome = await adapter.run(run.task_id, seams)
    return outcome, tape, seams.steps.steps


async def probe(
    adapter: AgentAdapter, run: PinnedRun, k: int, samples: int, config: ModelConfig
) -> ProbeResult:
    """`samples` live continuations after pinning `k` steps."""
    pinned_model_calls = sum(step.kind == "model" for step in run.steps[:k])
    continuations: list[Continuation] = []
    for _ in range(samples):
        started = time.monotonic()
        outcome, tape, steps = await continue_from(adapter, run, k, config)
        continuations.append(
            Continuation(
                failed=outcome.failed,
                live_model_calls=len(tape.exchanges) - pinned_model_calls,
                live_tool_calls=sum(step.kind == "tool" for step in steps[k:]),
                seconds=round(time.monotonic() - started, 3),
            )
        )
    return ProbeResult(k=k, continuations=continuations)
