"""What an agent adapter is given (`Seams`) and what it returns (`RunOutcome`)."""

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel
from pydantic_ai.models import Model
from tracefork import Tape
from tracefork.redact import Redactor

from afr.seams.model import TapeMode
from afr.seams.steps import StepLog
from afr.seams.tools import ServedHook, TapedMCPToolset


class RunOutcome(BaseModel):
    """The checker's verdict on one run."""

    failed: bool
    problems: list[str]
    final_answer: str
    # Tool calls as the tool side itself logged them (Flight School's shop
    # log, the gateway's audit log): checked against the tape, never taken from it.
    tool_calls_logged: int


@dataclass
class Seams:
    """The taped model, and a factory for taped toolsets, for one run."""

    tape: Tape
    mode: TapeMode
    steps: StepLog
    redactor: Redactor
    model: Model
    toolsets: list[TapedMCPToolset] = field(default_factory=list[TapedMCPToolset])

    def toolset(
        self, url: str, *, is_sandbox: bool, on_served: ServedHook | None = None, **options: Any
    ) -> TapedMCPToolset:
        """An MCP toolset on this run's tape; `options` go to PydanticAI's `MCPToolset`."""
        toolset = TapedMCPToolset(
            url,
            tape=self.tape,
            mode=self.mode,
            steps=self.steps,
            redactor=self.redactor,
            is_sandbox=is_sandbox,
            on_served=on_served,
            **options,
        )
        self.toolsets.append(toolset)
        return toolset
