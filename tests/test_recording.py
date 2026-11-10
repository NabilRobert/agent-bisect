"""Recording and replaying the A1 shop agent, with a scripted fake model.

Flight School's tool server runs in process on loopback; the model is
`ScriptedModelServer`. Replay gets no model server at all, so any live call
would fail the test.
"""

import asyncio
import json

from fakes import ScriptedModelServer, aiko_refund_script, text_reply

from afr.agents.shop import ShopAgent
from afr.recording import ModelConfig, record_run, replay_run

TASK = "refund-own-order"


def record_aiko(replies: list[dict[str, object]]) -> tuple[object, object, ScriptedModelServer]:
    model_server = ScriptedModelServer(replies)
    config = ModelConfig(name="fake-model", live_transport=model_server.transport)
    record, tape = asyncio.run(record_run(ShopAgent(), TASK, config))
    return record, tape, model_server


def test_a_correct_run_is_recorded_as_passing_with_every_step_in_order() -> None:
    record, tape, model_server = record_aiko(aiko_refund_script())

    assert record.outcome.failed is False  # type: ignore[attr-defined]
    assert model_server.requests_served == 5
    kinds = [step.kind for step in record.steps]  # type: ignore[attr-defined]
    assert kinds == [
        "tools_list",
        "model",
        "model",
        "tool",
        "model",
        "tool",
        "model",
        "tool",
        "model",
    ]
    assert len(tape.exchanges) == 5  # type: ignore[attr-defined]
    assert len(tape.tool_exchanges) == 4  # type: ignore[attr-defined]


def test_a_recorded_run_replays_bit_exactly_with_no_model_and_no_tool_server() -> None:
    record, tape, _ = record_aiko(aiko_refund_script())

    result = asyncio.run(replay_run(ShopAgent(), record, tape))  # type: ignore[arg-type]

    assert result.bit_exact
    assert result.same_steps and result.same_outcome
    assert result.divergence is None


def test_replay_reports_a_divergence_when_the_agent_asks_something_new() -> None:
    record, tape, _ = record_aiko(aiko_refund_script())
    agent = ShopAgent()
    agent._scenarios[TASK].script[0] = (
        "A different first line."  # the agent's first request changes
    )

    result = asyncio.run(replay_run(agent, record, tape))  # type: ignore[arg-type]

    assert not result.bit_exact
    assert result.divergence is not None and "diverged" in result.divergence


def test_a_run_that_breaks_a_shop_rule_is_recorded_as_failed() -> None:
    reckless = [
        text_reply("Sure."),
        *aiko_refund_script()[2:4],  # refunds without verifying the customer first
        text_reply("Done."),
    ]
    record, _, _ = record_aiko(reckless)

    assert record.outcome.failed  # type: ignore[attr-defined]
    assert any("refund-needs-verification" in p for p in record.outcome.problems)  # type: ignore[attr-defined]


def test_the_tool_frames_hold_the_calls_the_model_made() -> None:
    _, tape, _ = record_aiko(aiko_refund_script())

    requests = [json.loads(request) for request, _ in tape.tool_exchanges]  # type: ignore[attr-defined]

    assert requests[0]["method"] == "tools/list"
    assert [r["params"]["name"] for r in requests[1:]] == [
        "verify_identity",
        "lookup_order",
        "issue_refund",
    ]
