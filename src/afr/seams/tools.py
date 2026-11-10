"""The tool seam: an MCP toolset whose calls go through tracefork's tool tape (ADR-005).

tracefork tapes MCP as JSON-RPC frames (`ToolTransport`) but only if the
client is wrapped, and only `tools/call`. `TapedMCPToolset` overrides two
public methods of PydanticAI's `MCPToolset`:
- `list_tools`: taped once per run, so a replay needs no server;
- `direct_call_tool`: each call taped; a `process_tool_call` hook (Juku's
  token minting) still runs around it.

The `_meta` a hook adds goes to the live server but never into a frame, so a
delegation token is neither stored nor matched (threat T1). On replay the
toolset doesn't connect at all.
"""

from collections.abc import Callable
from typing import Any, Self

from mcp import types as mcp_types
from pydantic_ai import ModelRetry
from pydantic_ai.mcp import MCPToolset
from tracefork import Tape, ToolTransport
from tracefork.redact import Redactor
from tracefork.tools import (
    decode_result,
    make_request_frame,
    make_result_frame,
    make_tool_call_frame,
)

from afr.seams.model import TapeMode
from afr.seams.sandbox import check_live_call
from afr.seams.steps import StepLog

# Called with (tool name, arguments) each time a call is served from the tape,
# so an in-process fake world can apply it too (see agents/shop.py).
ServedHook = Callable[[str, dict[str, Any]], None]


class TapedMCPToolset(MCPToolset[Any]):
    """PydanticAI's MCP toolset, recorded to or replayed from a tracefork tape."""

    def __init__(  # noqa: PLR0913 - each argument is one part of the seam's wiring
        self,
        url: str,
        *,
        tape: Tape,
        mode: TapeMode,
        steps: StepLog,
        redactor: Redactor,
        is_sandbox: bool,
        on_served: ServedHook | None = None,
        **toolset_options: Any,
    ) -> None:
        # PydanticAI's signature names an optional fastmcp type pyright can't see.
        super().__init__(url, **toolset_options)  # pyright: ignore[reportUnknownMemberType]
        self._url = url
        self._mode: TapeMode = mode
        self._frames = ToolTransport(mode, tape, redactor=redactor)
        self._steps = steps
        self._is_sandbox = is_sandbox
        self._on_served = on_served
        self._tool_definitions: list[mcp_types.Tool] | None = None
        self._slots = FrameSlots(self._frames)

    async def __aenter__(self) -> Self:
        if self._mode == "replay":
            return self
        return await super().__aenter__()

    async def __aexit__(self, *args: Any) -> bool | None:
        if self._mode == "replay":
            return None
        return await super().__aexit__(*args)

    async def list_tools(self) -> list[mcp_types.Tool]:
        if self._tool_definitions is None:
            self._tool_definitions = await self._taped_tool_list()
        return self._tool_definitions

    async def direct_call_tool(
        self,
        name: str,
        args: dict[str, Any],
        *,
        metadata: dict[str, Any] | None = None,
        use_task: bool = False,
    ) -> Any:
        request = make_tool_call_frame(None, name, args)  # no `metadata`: see the module docstring
        if self._mode == "replay":
            self._steps.add("tool")
            payload = decode_result(self._frames.replay_exchange(request))
            if self._on_served is not None:
                self._on_served(name, args)
        else:
            payload = await self._record_call(name, args, request, metadata, use_task)
        return unwrap(payload)

    def frames_fully_consumed(self) -> bool:
        return self._frames.fully_consumed()

    async def _taped_tool_list(self) -> list[mcp_types.Tool]:
        request = make_request_frame(None, "tools/list")
        self._steps.add("tools_list")
        if self._mode == "replay":
            listed = decode_result(self._frames.replay_exchange(request))
            return [mcp_types.Tool.model_validate(tool) for tool in listed]
        live = await super().list_tools()
        dumped = [tool.model_dump(mode="json", by_alias=True) for tool in live]
        self._frames.record_exchange(request, make_result_frame(None, dumped))
        return live

    async def _record_call(
        self,
        name: str,
        args: dict[str, Any],
        request: bytes,
        metadata: dict[str, Any] | None,
        use_task: bool,
    ) -> dict[str, Any]:
        definitions = await self.list_tools()
        definition = next((tool for tool in definitions if tool.name == name), None)
        check_live_call(name, definition, self._url, self._is_sandbox)
        slot = self._slots.reserve()
        self._steps.add("tool")
        try:
            result = await super().direct_call_tool(
                name, args, metadata=metadata, use_task=use_task
            )
            payload: dict[str, Any] = {"ok": result}
        except ModelRetry as retry:  # a tool error the model is told about: part of the run
            payload = {"retry": str(retry)}
        self._slots.complete(slot, request, make_result_frame(None, payload))
        return payload


def unwrap(payload: dict[str, Any]) -> Any:
    """The tool's result, or the same `ModelRetry` the live call raised."""
    if "retry" in payload:
        raise ModelRetry(payload["retry"])
    return payload["ok"]


class FrameSlots:
    """Keeps tool frames in the order the calls started, not the order they finished.

    PydanticAI runs one response's tool calls concurrently; replay serves
    frames in the order calls arrive, which is the order they start. So a
    call takes its slot when it starts, and frames reach the tape in slot
    order once every earlier call has finished.
    """

    def __init__(self, frames: ToolTransport) -> None:
        self._frames = frames
        self._next_slot = 0
        self._next_to_write = 0
        self._finished: dict[int, tuple[bytes, bytes]] = {}

    def reserve(self) -> int:
        slot = self._next_slot
        self._next_slot += 1
        return slot

    def complete(self, slot: int, request: bytes, response: bytes) -> None:
        self._finished[slot] = (request, response)
        while self._next_to_write in self._finished:
            self._frames.record_exchange(*self._finished.pop(self._next_to_write))
            self._next_to_write += 1
