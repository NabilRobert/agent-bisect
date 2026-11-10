"""The order of a run's steps across tracefork's two exchange lists.

tracefork's tape holds model exchanges and tool frames in separate lists
(`Tape.exchanges`, `Tape.tool_exchanges`), each numbered from 0. A step in
this repo is one entry in the combined order, so "pin the first k steps"
means the same thing whatever mix of model and tool calls comes first.
"""

from typing import Literal

from pydantic import BaseModel

StepKind = Literal["model", "tool", "tools_list"]


class Step(BaseModel):
    """One step: which list it is in, and its index there.

    `tools_list` is the agent asking for the tool definitions: taped so a
    replay needs no server, but not a decision, so bisection skips it.
    """

    kind: StepKind
    index: int


class StepLog:
    """Steps in the order they happened, numbered per list as tracefork numbers them."""

    def __init__(self) -> None:
        self.steps: list[Step] = []
        self._counts: dict[StepKind, int] = {"model": 0, "tool": 0, "tools_list": 0}

    def add(self, kind: StepKind) -> Step:
        list_name: StepKind = "tool" if kind == "tools_list" else kind
        # Tool calls and tools/list frames share tracefork's one tool list.
        index = self._counts[list_name]
        self._counts[list_name] = index + 1
        step = Step(kind=kind, index=index)
        self.steps.append(step)
        return step
