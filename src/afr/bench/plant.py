"""Fault plans: where each fault type goes in a clean run, and what replaces it.

For each fault type the eligible steps are found (`eligible_steps`); the
"early" position is the first, the "late" position the last, so early
faults sit far from where the failure shows. F5's replacement is the
model's live answer to the shortened request, fetched once here; every
other replacement is computed from the clean run.
"""

import base64
from typing import Literal

import httpx2
from tracefork import Tape

from afr.agents import AgentAdapter
from afr.faults import (
    MODEL_FAULTS,
    TOOL_FAULTS,
    FaultPlan,
    FaultType,
    response_of,
    tool_fault,
    without_earlier_messages,
    wrong_decision,
)
from afr.probing import PinnedRun
from afr.recording import ModelConfig
from afr.runs import RunRecord
from afr.seams.model import PLACEHOLDER_API_KEY

Position = Literal["early", "late"]


def replacement_for(clean: PinnedRun, step: int, fault: FaultType, injection: str) -> bytes | None:
    """The deterministic replacement (F1-F4), or None where the fault doesn't apply."""
    kind = clean.steps[step].kind
    response = response_of(clean, step)
    if fault in TOOL_FAULTS:
        return tool_fault(fault, response, injection) if kind == "tool" else None
    if fault == "F4":
        return wrong_decision(response) if kind == "model" else None
    return None


def shortened_request(clean: PinnedRun, step: int) -> bytes | None:
    """F5's request at a model step, or None if nothing earlier could be dropped."""
    planted = clean.steps[step]
    if planted.kind != "model":
        return None
    request, _ = clean.tape.exchanges[planted.index]
    return without_earlier_messages(request)


def eligible_steps(clean: PinnedRun, fault: FaultType, injection: str) -> list[int]:
    steps = range(len(clean.steps))
    if fault == "F5":
        return [step for step in steps if shortened_request(clean, step) is not None]
    return [step for step in steps if replacement_for(clean, step, fault, injection) is not None]


def positions(eligible: list[int]) -> dict[Position, int]:
    if not eligible:
        return {}
    if len(eligible) == 1:
        return {"early": eligible[0]}
    return {"early": eligible[0], "late": eligible[-1]}


async def live_reply(request: bytes, config: ModelConfig) -> bytes:
    """One live, non-streamed chat completion for `request`."""
    transport = config.live_transport or httpx2.AsyncHTTPTransport()
    headers = {"content-type": "application/json", "authorization": f"Bearer {PLACEHOLDER_API_KEY}"}
    async with httpx2.AsyncClient(transport=transport, timeout=120.0) as client:
        response = await client.post(
            f"{config.base_url}/chat/completions", content=request, headers=headers
        )
    response.raise_for_status()
    return response.content


def pinned(record: RunRecord, tape: Tape) -> PinnedRun:
    return PinnedRun(tape=tape, steps=record.steps, task_id=record.task_id, model=record.model)


async def plan_faults(
    adapter: AgentAdapter, record: RunRecord, tape: Tape, config: ModelConfig
) -> list[FaultPlan]:
    """Every fault type at its early and late position in one clean run."""
    clean = pinned(record, tape)
    injection = adapter.injection
    plans: list[FaultPlan] = []
    for fault in (*TOOL_FAULTS, *MODEL_FAULTS):
        for position, step in positions(eligible_steps(clean, fault, injection)).items():
            if fault == "F5":
                shortened = shortened_request(clean, step)
                assert shortened is not None  # eligible_steps checked it
                replacement = await live_reply(shortened, config)
            else:
                replacement = replacement_for(clean, step, fault, injection)
                assert replacement is not None
            plans.append(
                FaultPlan(
                    fault_id=f"{adapter.name}-{clean.task_id}-{fault}-{position}",
                    agent=adapter.name,
                    task_id=clean.task_id,
                    clean_run_id=record.run_id,
                    clean_tape_digest=record.tape_digest,
                    step=step,
                    fault=fault,
                    position=position,
                    replacement_b64=base64.b64encode(replacement).decode(),
                    description=f"{fault} at step {step} ({clean.steps[step].kind}), {position}",
                )
            )
    return plans
