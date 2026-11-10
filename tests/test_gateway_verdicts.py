"""Reading mcp-gateway's audit log into one verdict per taped tool step.

The lines below have the shape mcp-gateway writes (a `call` line, then a
`result` line with the same `call_id`); the gateway itself is a private
repo and isn't run in CI.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from tracefork import Tape
from tracefork.tools import make_request_frame, make_result_frame, make_tool_call_frame

from afr.gateway.stack import gateway_config
from afr.gateway.verdicts import (
    AuditMismatch,
    audited_calls,
    match_verdicts,
    read_lines_since,
    taped_tool_calls,
)


def call_line(
    call_id: str, tool: str, arguments: dict[str, Any], caller: str = "afr"
) -> dict[str, Any]:
    return {
        "kind": "call",
        "call_id": call_id,
        "caller": caller,
        "tool": tool,
        "arguments": arguments,
        "decision": "forwarding",
    }


def result_line(call_id: str, decision: str, suspicious: bool) -> dict[str, Any]:
    return {
        "kind": "result",
        "call_id": call_id,
        "decision": decision,
        "suspicious": suspicious,
        "layer": "rules",
    }


def test_each_call_gets_the_decision_from_its_result_line() -> None:
    lines = [
        call_line("a", "lookup_order", {"order_id": "o4"}),
        call_line("b", "issue_refund", {"order_id": "o4", "amount_cents": 1200}),
        result_line("b", "allowed", suspicious=False),
        result_line("a", "logged", suspicious=True),
    ]

    calls = audited_calls(lines, "afr")

    assert [(tool, verdict.decision, verdict.suspicious) for tool, _, verdict in calls] == [
        ("lookup_order", "logged", True),
        ("issue_refund", "allowed", False),
    ]


def test_a_refused_call_keeps_its_own_decision_and_no_scan() -> None:
    lines = [{**call_line("a", "delete_account", {"customer_id": "c1"}), "decision": "denied"}]

    [(_, _, verdict)] = audited_calls(lines, "afr")

    assert verdict.decision == "denied" and verdict.suspicious is None


def test_another_callers_calls_are_left_out() -> None:
    lines = [call_line("a", "lookup_order", {"order_id": "o1"}, caller="someone-else")]

    assert audited_calls(lines, "afr") == []


def test_verdicts_line_up_with_the_taped_calls_when_both_agree() -> None:
    audited = audited_calls(
        [call_line("a", "lookup_order", {"order_id": "o1"}), result_line("a", "allowed", False)],
        "afr",
    )

    [verdict] = match_verdicts([("lookup_order", {"order_id": "o1"})], audited)

    assert verdict.tool == "lookup_order" and verdict.decision == "allowed"


def test_a_call_missing_from_the_audit_log_is_an_error() -> None:
    with pytest.raises(AuditMismatch, match="the tape has 1 tool calls but the gateway audited 0"):
        match_verdicts([("lookup_order", {"order_id": "o1"})], [])


def test_different_arguments_in_the_audit_log_are_an_error() -> None:
    audited = audited_calls([call_line("a", "lookup_order", {"order_id": "o2"})], "afr")

    with pytest.raises(AuditMismatch, match="tool call 0"):
        match_verdicts([("lookup_order", {"order_id": "o1"})], audited)


def test_only_lines_written_after_the_offset_are_read(tmp_path: Path) -> None:
    log = tmp_path / "audit.jsonl"
    log.write_text(json.dumps(call_line("old", "lookup_order", {})) + "\n")
    offset = log.stat().st_size
    with log.open("a") as appending:
        appending.write(json.dumps(call_line("new", "list_orders", {})) + "\n")

    assert [line["call_id"] for line in read_lines_since(log, offset)] == ["new"]


def test_the_taped_calls_skip_the_tool_list() -> None:
    tape = Tape()
    tape.append_tool_exchange(make_request_frame(None, "tools/list"), make_result_frame(None, []))
    tape.append_tool_exchange(make_tool_call_frame(None, "lookup_order", {"order_id": "o1"}), b"{}")

    assert taped_tool_calls(tape) == [("lookup_order", {"order_id": "o1"})]


def test_the_gateway_config_logs_suspicious_outputs_and_stores_only_the_keys_hash() -> None:
    config = yaml.safe_load(
        gateway_config("http://127.0.0.1:1/mcp?conversation=t", "the-key", Path("a.jsonl"), None)
    )

    assert config["policies"]["bench"]["on_suspicious"] == "log"
    assert config["callers"]["afr"]["key_sha256"] == hashlib.sha256(b"the-key").hexdigest()
    assert "the-key" not in yaml.safe_dump(config)
    assert "issue_refund" in config["policies"]["bench"]["routes"]["shop"]["tools"]
