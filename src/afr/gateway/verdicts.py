"""The gateway's verdict on each tool step, read from its audit log.

mcp-gateway writes a `call` line (tool, arguments) before it forwards a
call and a `result` line (decision; whether the detector found the output
suspicious, and which layer) after, joined by `call_id`. The log has no run
id, so runs go one at a time and only the lines written during the run are
read (from a byte offset). Audited calls are matched to taped tool calls in
order, and each pair must agree on tool and arguments: a mismatch is an
error, never a silently wrong verdict.
"""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from tracefork import Tape


class ToolVerdict(BaseModel):
    """What the gateway decided about one tool call."""

    tool: str
    decision: str  # allowed, blocked, annotated, logged, denied, rate_limited, gateway_error
    suspicious: bool | None  # None when no output was scanned (a refused call)
    layer: str | None  # the detector layer that ran: rules or model


class AuditMismatch(RuntimeError):
    """The audit log and the tape disagree about which tool calls were made."""


AuditedCall = tuple[str, dict[str, Any], ToolVerdict]


def read_lines_since(path: Path, offset: int) -> list[dict[str, Any]]:
    with path.open("rb") as log:
        log.seek(offset)
        text = log.read().decode()
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def audited_calls(lines: list[dict[str, Any]], caller: str) -> list[AuditedCall]:
    """(tool, arguments, verdict) for each call `caller` made, in the order they were made."""
    results = {line["call_id"]: line for line in lines if line.get("kind") == "result"}
    calls: list[AuditedCall] = []
    for line in lines:
        if line.get("kind") != "call" or line.get("caller") != caller:
            continue
        result = results.get(line.get("call_id", ""))
        # A refused call has no result line: its own decision says why.
        source = result if result is not None else line
        verdict = ToolVerdict(
            tool=line["tool"],
            decision=source["decision"],
            suspicious=source.get("suspicious"),
            layer=source.get("layer"),
        )
        calls.append((line["tool"], line.get("arguments", {}), verdict))
    return calls


def taped_tool_calls(tape: Tape) -> list[tuple[str, dict[str, Any]]]:
    """(tool, arguments) for each `tools/call` frame on the tape, in order."""
    calls: list[tuple[str, dict[str, Any]]] = []
    for request, _ in tape.tool_exchanges:
        frame = json.loads(request)
        if frame.get("method") == "tools/call":
            calls.append((frame["params"]["name"], frame["params"]["arguments"]))
    return calls


def match_verdicts(
    taped: list[tuple[str, dict[str, Any]]], audited: list[AuditedCall]
) -> list[ToolVerdict]:
    """One verdict per taped tool call, after checking the two lists name the same calls."""
    if len(taped) != len(audited):
        raise AuditMismatch(
            f"the tape has {len(taped)} tool calls but the gateway audited {len(audited)}: "
            "another client may be using the gateway, or a call bypassed it"
        )
    verdicts: list[ToolVerdict] = []
    for position, ((tool, arguments), (audited_tool, audited_arguments, verdict)) in enumerate(
        zip(taped, audited, strict=True)
    ):
        if (tool, arguments) != (audited_tool, audited_arguments):
            raise AuditMismatch(
                f"tool call {position}: the tape has {tool}({arguments}) "
                f"but the gateway audited {audited_tool}({audited_arguments})"
            )
        verdicts.append(verdict)
    return verdicts
