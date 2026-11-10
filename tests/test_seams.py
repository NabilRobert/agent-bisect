"""The seams' safety rules: secrets never taped (T1), no live writes outside a sandbox (T3),
and tool frames kept in the order calls started."""

import asyncio
from typing import Any

import pytest
from fakes import ScriptedModelServer, aiko_refund_script, text_reply, tool_call_reply
from flight_school.conversation.agent import AgentTools
from flight_school.http.tool_server import running_tool_server
from flight_school.world.schema import load_world
from flight_school.world.shop import FakeShop
from mcp import types as mcp_types
from pydantic_ai import Agent, RunContext
from pydantic_ai.mcp import CallToolFunc
from tracefork import Tape, ToolTransport

from afr.agents.shop import WORLD_DIR, ShopAgent
from afr.recording import ModelConfig, build_seams, record_run, replay_run
from afr.seams.sandbox import SandboxViolation, check_live_call
from afr.seams.steps import StepLog
from afr.seams.tools import FrameSlots

# Shaped like real secrets so the patterns must catch them; none is real.
CANARY_API_KEY = "sk-canary" + "0123456789abcdefghijkl"
# Not secret-shaped on purpose: only the frame rule, not the secret patterns, may keep it out.
CANARY_META_TOKEN = "delegation-canary-7f3a91"


def every_taped_byte(tape: Tape) -> bytes:
    pairs = [*tape.exchanges, *tape.tool_exchanges]
    return b"".join(request + response for request, response in pairs)


def test_an_api_key_in_a_model_reply_is_stripped_and_the_run_still_replays() -> None:
    model_server = ScriptedModelServer(aiko_refund_script(api_key_in_reply=CANARY_API_KEY))
    config = ModelConfig(name="fake-model", live_transport=model_server.transport)
    record, tape = asyncio.run(record_run(ShopAgent(), "refund-own-order", config))

    assert CANARY_API_KEY.encode() not in every_taped_byte(tape)
    assert CANARY_API_KEY not in record.model_dump_json()
    assert asyncio.run(replay_run(ShopAgent(), record, tape)).bit_exact


async def call_with_minted_token(
    _ctx: RunContext[Any], call_tool: CallToolFunc, name: str, arguments: dict[str, Any]
) -> Any:
    """Like Juku's `mint_and_record`: a fresh token in each call's `_meta`."""
    return await call_tool(name, arguments, metadata={"io.example/delegation": CANARY_META_TOKEN})


async def run_with_meta_hook(tape: Tape) -> list[str]:
    shop = FakeShop(load_world(WORLD_DIR / "world.yaml"))
    model_server = ScriptedModelServer(
        [tool_call_reply("lookup_order", {"order_id": "o1"}, "call_1"), text_reply("It is $45.")]
    )
    config = ModelConfig(name="fake-model", live_transport=model_server.transport)
    seams, _ = build_seams(tape, "record", config)
    with running_tool_server() as server:
        url = server.register(AgentTools(shop))
        toolset = seams.toolset(url, is_sandbox=True, process_tool_call=call_with_minted_token)
        await Agent(seams.model, toolsets=[toolset]).run("What did order o1 cost?")
    return [call.tool for call in shop.calls]


def test_a_meta_delegation_token_reaches_the_tool_but_never_the_tape() -> None:
    tape = Tape()

    calls = asyncio.run(run_with_meta_hook(tape))

    assert calls == ["lookup_order"]
    assert CANARY_META_TOKEN.encode() not in every_taped_byte(tape)


async def run_destructive_call_outside_sandbox() -> FakeShop:
    shop = FakeShop(load_world(WORLD_DIR / "world.yaml"))
    model_server = ScriptedModelServer(
        [tool_call_reply("delete_account", {"customer_id": "c1"}, "call_1")]
    )
    config = ModelConfig(name="fake-model", live_transport=model_server.transport)
    seams, _ = build_seams(Tape(), "record", config)
    with running_tool_server() as server:
        toolset = seams.toolset(server.register(AgentTools(shop)), is_sandbox=False)
        with pytest.raises(BaseException) as raised:
            await Agent(seams.model, toolsets=[toolset]).run("Delete my account.")
    assert "refused live call to 'delete_account'" in repr(raised.value) or isinstance(
        raised.value, SandboxViolation
    )
    return shop


def test_a_destructive_tool_is_refused_live_outside_a_sandbox() -> None:
    shop = asyncio.run(run_destructive_call_outside_sandbox())

    assert shop.calls == []


def test_a_read_only_tool_may_run_live_outside_a_sandbox() -> None:
    read_only = mcp_types.Tool(
        name="lookup_order",
        input_schema={"type": "object"},
        annotations=mcp_types.ToolAnnotations.model_validate({"readOnlyHint": True}),
    )

    check_live_call("lookup_order", read_only, "http://tools.example/mcp", is_sandbox=False)


def test_an_unannotated_tool_is_refused_outside_a_sandbox() -> None:
    unannotated = mcp_types.Tool(name="issue_refund", input_schema={"type": "object"})

    with pytest.raises(SandboxViolation):
        check_live_call("issue_refund", unannotated, "http://tools.example/mcp", is_sandbox=False)


def test_tool_frames_reach_the_tape_in_the_order_calls_started() -> None:
    tape = Tape()
    slots = FrameSlots(ToolTransport("record", tape))
    first, second = slots.reserve(), slots.reserve()

    slots.complete(second, b"second-request", b"second-response")
    assert tape.tool_exchanges == []  # held back until the earlier call finishes
    slots.complete(first, b"first-request", b"first-response")

    assert [request for request, _ in tape.tool_exchanges] == [b"first-request", b"second-request"]


def test_steps_are_numbered_as_tracefork_numbers_its_two_lists() -> None:
    steps = StepLog()
    for kind in ("tools_list", "model", "tool", "model", "tool"):
        steps.add(kind)  # type: ignore[arg-type]

    numbered = [(step.kind, step.index) for step in steps.steps]

    assert numbered == [("tools_list", 0), ("model", 0), ("tool", 1), ("model", 1), ("tool", 2)]
