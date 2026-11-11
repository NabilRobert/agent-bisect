"""Probes on A1: pin k steps of a recorded run, continue live with a scripted model."""

import asyncio

import httpx2
import pytest
from fakes import ScriptedModelServer, aiko_refund_script, text_reply, tool_call_reply
from tracefork import Tape

from afr.agents.shop import ShopAgent
from afr.probing import PinnedRun, continue_from, prefix_tape, probe
from afr.recording import ModelConfig, build_seams, record_run
from afr.seams.sandbox import SandboxViolation

TASK = "refund-own-order"
# Recorded steps of the aiko script:
# 0 tools_list, 1 model (asks email), 2 model (verify), 3 tool (verify), 4 model (lookup),
# 5 tool (lookup), 6 model (refund), 7 tool (refund), 8 model (confirms)
AFTER_VERIFY = 4


def recorded_aiko() -> PinnedRun:
    config = ModelConfig(
        name="fake-model", live_transport=ScriptedModelServer(aiko_refund_script()).transport
    )
    record, tape = asyncio.run(record_run(ShopAgent(), TASK, config))
    return PinnedRun(tape=tape, steps=record.steps, task_id=TASK, model=record.model)


def probe_with(
    run: PinnedRun, k: int, live_replies: list[dict[str, object]]
) -> tuple[object, ScriptedModelServer]:
    model_server = ScriptedModelServer(live_replies)
    config = ModelConfig(live_transport=model_server.transport)
    return asyncio.run(probe(ShopAgent(), run, k, samples=1, config=config)), model_server


def test_pinning_every_step_reproduces_the_run_with_no_live_call() -> None:
    run = recorded_aiko()

    result, model_server = probe_with(run, len(run.steps), [])

    assert model_server.requests_served == 0
    assert result.failure_rate == 0.0  # type: ignore[attr-defined]


def test_pinning_no_steps_runs_the_whole_task_live() -> None:
    run = recorded_aiko()

    result, model_server = probe_with(run, 0, aiko_refund_script())

    assert model_server.requests_served == 5
    assert result.continuations[0].live_tool_calls == 3  # type: ignore[attr-defined]


def test_a_continuation_goes_live_after_the_pinned_steps_on_the_same_shop() -> None:
    run = recorded_aiko()
    over_the_total = [
        tool_call_reply("lookup_order", {"order_id": "o1"}, "call_2"),
        tool_call_reply("issue_refund", {"order_id": "o1", "amount_cents": 9000}, "call_3"),
        text_reply("Refunded."),
    ]

    result, model_server = probe_with(run, AFTER_VERIFY, over_the_total)

    continuation = result.continuations[0]  # type: ignore[attr-defined]
    assert model_server.requests_served == 3
    assert continuation.failed
    assert result.failure_rate == 1.0  # type: ignore[attr-defined]
    assert (continuation.live_model_calls, continuation.live_tool_calls) == (3, 2)


def test_a_pinned_step_is_applied_to_the_shop_so_the_checker_sees_it() -> None:
    run = recorded_aiko()
    rest_of_a_correct_run = aiko_refund_script()[2:]

    result, _ = probe_with(run, AFTER_VERIFY, rest_of_a_correct_run)

    # verify_identity was served from the tape, not called live; the refund after it
    # still counts as verified only if the pinned call reached the shop.
    assert result.failure_rate == 0.0  # type: ignore[attr-defined]


def test_the_prefix_holds_exactly_the_pinned_steps() -> None:
    run = recorded_aiko()

    prefix = prefix_tape(run, AFTER_VERIFY)

    assert len(prefix.exchanges) == 2  # the two model steps among the first four
    assert len(prefix.tool_exchanges) == 2  # the tool listing and verify_identity


def test_a_probe_refuses_tools_that_are_not_a_sandbox() -> None:
    seams, _ = build_seams(Tape(), "pin", ModelConfig(), ShopAgent.model_settings)

    with pytest.raises(SandboxViolation, match="refused to probe"):
        seams.toolset("http://tools.example/mcp", is_sandbox=False)


def test_pinned_tool_calls_are_served_from_the_tape_not_called_again() -> None:
    run = recorded_aiko()
    config = ModelConfig(live_transport=ScriptedModelServer([]).transport)

    _, tape, _ = asyncio.run(continue_from(ShopAgent(), run, len(run.steps), config))

    assert tape.tool_exchanges == run.tape.tool_exchanges  # nothing re-recorded


class BrokenModelServer:
    """Answers every request the way Ollama does when it can't parse the model's tool call."""

    def __init__(self) -> None:
        body = {"error": {"message": "XML syntax error on line 10: unexpected EOF"}}
        self.transport = httpx2.MockTransport(lambda _request: httpx2.Response(500, json=body))


def test_a_model_error_in_a_continuation_counts_as_a_failure_not_a_crash() -> None:
    run = recorded_aiko()
    config = ModelConfig(live_transport=BrokenModelServer().transport)

    result = asyncio.run(probe(ShopAgent(), run, AFTER_VERIFY, samples=2, config=config))

    assert result.failure_rate == 1.0


def test_a_model_error_while_recording_is_a_failed_run() -> None:
    config = ModelConfig(name="fake-model", live_transport=BrokenModelServer().transport)

    record, _ = asyncio.run(record_run(ShopAgent(), TASK, config))

    assert record.outcome.failed
    assert record.outcome.problems[0].startswith("model error: ModelHTTPError")


def test_a_divergence_in_the_pinned_steps_still_stops_the_probe() -> None:
    run = recorded_aiko()
    changed = ShopAgent()
    changed._scenarios[TASK].script[0] = (
        "A different first line."  # the first pinned request changes
    )
    config = ModelConfig(live_transport=ScriptedModelServer([]).transport)

    with pytest.raises(BaseException, match="diverged"):
        asyncio.run(probe(changed, run, AFTER_VERIFY, samples=1, config=config))
