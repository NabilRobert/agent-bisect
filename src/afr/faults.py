"""Planted faults (measurement plan): replace one step's response in a clean run.

A fault is planted at step `k` of a clean recorded run: steps `0 … k-1` are
kept exactly, step `k` keeps its request but gets a different response, and
everything after is left to a live continuation (a probe pinning `k+1`
steps). The five types:

| Type | At | Replacement |
|---|---|---|
| F1 | tool step | the result with one value wrong (a number x10, or a yes/no flipped) |
| F2 | tool step | a tool error ("upstream timeout") |
| F3 | tool step | the result with an instruction added (the agent's `injection`) |
| F4 | model step | a wrong decision: a number in the tool call x10, else an early answer |
| F5 | model step | the model's live answer to the request with earlier messages dropped |

Every builder is deterministic except F5, which needs one live model call
when the plan is made; the replacement bytes go into the frozen plan.
"""

import base64
import copy
import json
from collections.abc import Callable
from typing import Any, Literal, cast

from pydantic import BaseModel
from tracefork.tools import decode_result, make_result_frame

from afr.probing import PinnedRun, prefix_tape

FaultType = Literal["F1", "F2", "F3", "F4", "F5"]
TOOL_FAULTS: tuple[FaultType, ...] = ("F1", "F2", "F3")
MODEL_FAULTS: tuple[FaultType, ...] = ("F4", "F5")
WRONG_FACTOR = 10  # "price 25.000 becomes 250.000"
TOOL_ERROR = "upstream timeout: the backend did not answer"
EARLY_ANSWER = "I have checked everything and it is all done."


class FaultPlan(BaseModel):
    """One planted fault, as frozen data."""

    fault_id: str
    agent: str
    task_id: str
    clean_run_id: str
    clean_tape_digest: str
    step: int
    fault: FaultType
    position: Literal["early", "late"]
    replacement_b64: str
    description: str

    @property
    def replacement(self) -> bytes:
        return base64.b64decode(self.replacement_b64)


def planted_run(clean: PinnedRun, step: int, replacement: bytes) -> PinnedRun:
    """The clean run's first `step` steps, then step `step` with `replacement` as its response."""
    tape = prefix_tape(clean, step)
    planted = clean.steps[step]
    if planted.kind == "model":
        request, _ = clean.tape.exchanges[planted.index]
        tape.exchanges.append((request, replacement))
    else:
        request, _ = clean.tape.tool_exchanges[planted.index]
        tape.tool_exchanges.append((request, replacement))
    return PinnedRun(
        tape=tape, steps=clean.steps[: step + 1], task_id=clean.task_id, model=clean.model
    )


def response_of(run: PinnedRun, step: int) -> bytes:
    planted = run.steps[step]
    exchanges = run.tape.exchanges if planted.kind == "model" else run.tape.tool_exchanges
    return exchanges[planted.index][1]


def tool_fault(fault: FaultType, response: bytes, injection: str) -> bytes | None:
    """F1-F3's replacement for a tool step's response frame, or None if it doesn't apply."""
    decoded: Any = decode_result(response)
    if not isinstance(decoded, dict) or "ok" not in decoded:
        return None  # a step that already failed can't be made to fail differently
    result: Any = cast(dict[str, Any], decoded)["ok"]
    if fault == "F2":
        return make_result_frame(None, {"retry": TOOL_ERROR})
    if fault == "F3":
        return make_result_frame(None, {"ok": with_injection(result, injection)})
    wrong = with_one_value_wrong(result)
    return None if wrong is None else make_result_frame(None, {"ok": wrong})


def with_injection(result: Any, injection: str) -> Any:
    if isinstance(result, dict):
        return {**cast(dict[str, Any], result), "note": injection}
    return f"{result}\n{injection}"


def with_one_value_wrong(value: Any) -> Any | None:
    """A copy with the first number (not an id) x10, else the first yes/no flipped."""
    wrong = copy.deepcopy(value)
    for change in (multiply_first_number, flip_first_flag):
        if change(wrong):
            return wrong
    return None


def is_number(leaf: Any) -> bool:
    return isinstance(leaf, int | float) and not isinstance(leaf, bool)


def multiply_first_number(value: Any) -> bool:
    return change_first(value, is_number, lambda leaf: leaf * WRONG_FACTOR)


def flip_first_flag(value: Any) -> bool:
    return change_first(value, lambda leaf: isinstance(leaf, bool), lambda leaf: not leaf)


def change_first(value: Any, matches: Callable[[Any], bool], change: Callable[[Any], Any]) -> bool:
    """Change the first matching leaf of nested dicts and lists in place; ids are left alone."""
    if isinstance(value, dict):
        mapping = cast(dict[str, Any], value)
        for key, leaf in mapping.items():
            if not key.endswith("id") and matches(leaf):
                mapping[key] = change(leaf)
                return True
            if change_first(leaf, matches, change):
                return True
    if isinstance(value, list):
        items = cast(list[Any], value)
        for position, leaf in enumerate(items):
            if matches(leaf):
                items[position] = change(leaf)
                return True
            if change_first(leaf, matches, change):
                return True
    return False


def wrong_decision(response: bytes) -> bytes | None:
    """F4: a tool call with a number x10, or else an early answer instead of the call."""
    completion: dict[str, Any] = json.loads(response)
    message: dict[str, Any] = completion["choices"][0]["message"]
    calls: list[dict[str, Any]] = message.get("tool_calls") or []
    if not calls:
        return None  # a final answer: there is no decision left to get wrong
    arguments = json.loads(calls[0]["function"]["arguments"])
    if multiply_first_number(arguments):
        calls[0]["function"]["arguments"] = json.dumps(arguments)
    else:
        completion["choices"][0]["message"] = {"role": "assistant", "content": EARLY_ANSWER}
        completion["choices"][0]["finish_reason"] = "stop"
    return json.dumps(completion).encode()


def without_earlier_messages(request: bytes) -> bytes | None:
    """F5's request: earlier messages dropped, keeping the system prompt and a valid sequence.

    Keeps the latest user message onwards; in a single-turn run, keeps the
    question and the latest tool call onwards. None if nothing would go.
    """
    body = json.loads(request)
    messages: list[dict[str, Any]] = body["messages"]
    system = [m for m in messages if m["role"] == "system"]
    rest = [m for m in messages if m["role"] != "system"]
    users = [i for i, m in enumerate(rest) if m["role"] == "user"]
    calls = [i for i, m in enumerate(rest) if m["role"] == "assistant" and m.get("tool_calls")]
    if len(users) > 1:
        kept = rest[users[-1] :]
    elif users and calls and calls[-1] > users[0] + 1:
        kept = [rest[users[0]], *rest[calls[-1] :]]
    else:
        return None
    body["messages"] = [*system, *kept]
    return json.dumps(body).encode()
