"""Test doubles: a scripted OpenAI-compatible model server, in process.

It answers chat-completion requests from a fixed list of replies, in order,
and counts the requests it served, so a test can check how many calls went
"live". No network, no model.
"""

import json
from typing import Any

import httpx2


def text_reply(text: str) -> dict[str, Any]:
    return {"role": "assistant", "content": text}


def tool_call_reply(name: str, arguments: dict[str, Any], call_id: str) -> dict[str, Any]:
    function = {"name": name, "arguments": json.dumps(arguments)}
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": call_id, "type": "function", "function": function}],
    }


def chat_completion(message: dict[str, Any], number: int) -> dict[str, Any]:
    finish_reason = "tool_calls" if message.get("tool_calls") else "stop"
    return {
        "id": f"chatcmpl-fake-{number}",
        "object": "chat.completion",
        "created": 0,
        "model": "fake-model",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


class ScriptedModelServer:
    """Serves `replies` one per request; `requests_served` counts live calls."""

    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self._replies = list(replies)
        self.requests_served = 0
        self.transport = httpx2.MockTransport(self._handle)

    def _handle(self, _request: httpx2.Request) -> httpx2.Response:
        if self.requests_served >= len(self._replies):
            raise AssertionError(
                f"the script has {len(self._replies)} replies; got one request too many"
            )
        reply = self._replies[self.requests_served]
        self.requests_served += 1
        return httpx2.Response(200, json=chat_completion(reply, self.requests_served))


def aiko_refund_script(api_key_in_reply: str = "") -> list[dict[str, Any]]:
    """A correct run of Flight School's `refund-own-order` scenario, as model replies.

    Turn 1: ask for the email. Turn 2: verify, look up, refund 4500, confirm.
    `api_key_in_reply` puts a secret in the last reply's text, for the canary test.
    """
    return [
        text_reply("Happy to help. What is the email on your account?"),
        tool_call_reply(
            "verify_identity", {"customer_id": "c1", "email": "aiko@example.com"}, "call_1"
        ),
        tool_call_reply("lookup_order", {"order_id": "o1"}, "call_2"),
        tool_call_reply("issue_refund", {"order_id": "o1", "amount_cents": 4500}, "call_3"),
        text_reply(f"Refunded 4500 cents for order o1. {api_key_in_reply}".strip()),
    ]
