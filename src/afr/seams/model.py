"""The model seam: tracefork's transport under PydanticAI's OpenAI client (ADR-004).

tracefork's own PydanticAI adapter fails in both modes on pydantic-ai 2.66
(ADR-001, bugs 1 and 2), so this builds tracefork's `AsyncTraceforkTransport`
directly and hands it to `OpenAIProvider` as its HTTP client: the same seam,
without the adapter's search for the client attribute.

Three modes: `record` (live, taped), `replay` (served from the tape, no
network) and `pin` (a probe: the tape's exchanges are served with tracefork's
hash check, then the run goes live and the new exchanges are taped). `pin`
is tracefork's `new_episodes` mode, which only its sync transport has, so it
runs in a worker thread under the async agent.
"""

import asyncio
from collections.abc import Callable
from typing import Literal

import httpx2
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings
from tracefork import Tape
from tracefork.redact import Redactor
from tracefork.transport import AsyncTraceforkTransport, TraceforkTransport

from afr.seams.steps import StepLog

TapeMode = Literal["record", "replay", "pin"]

# Ollama ignores the key, but the OpenAI client insists on one.
PLACEHOLDER_API_KEY = "ollama"


class StepLoggingTransport(httpx2.AsyncBaseTransport):
    """Notes each model exchange in the step log once tracefork has handled it."""

    def __init__(
        self, inner: httpx2.AsyncBaseTransport, steps: StepLog, consumed: Callable[[], bool]
    ) -> None:
        self._inner = inner
        self._steps = steps
        self._consumed = consumed

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        response = await self._inner.handle_async_request(request)
        self._steps.add("model")
        return response

    def fully_consumed(self) -> bool:
        """Replay only: whether every taped exchange was served."""
        return self._consumed()


class ThreadedTransport(httpx2.AsyncBaseTransport):
    """Runs a sync transport in a worker thread, for an async client."""

    def __init__(self, sync: httpx2.BaseTransport) -> None:
        self._sync = sync

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        await request.aread()
        response = await asyncio.to_thread(self._sync.handle_request, request)
        content = await asyncio.to_thread(response.read)
        return httpx2.Response(
            response.status_code, headers=response.headers, content=content, request=request
        )


def model_transport(
    tape: Tape,
    mode: TapeMode,
    steps: StepLog,
    redactor: Redactor,
    live: httpx2.MockTransport | None = None,
) -> StepLoggingTransport:
    """Record or pin through `live` (the real network by default), or replay from `tape`.

    Replay has no inner transport, so a request the tape doesn't hold is an
    error, never a live call (tracefork's contract). `live` is a test double.
    """
    matcher = redactor.matcher()
    if mode == "pin":
        live_sync = live or httpx2.HTTPTransport()
        sync = TraceforkTransport(
            "new_episodes", tape, live_sync, matcher=matcher, redactor=redactor
        )
        return StepLoggingTransport(ThreadedTransport(sync), steps, sync.fully_consumed)
    inner = (live or httpx2.AsyncHTTPTransport()) if mode == "record" else None
    traced = AsyncTraceforkTransport(mode, tape, inner, matcher=matcher, redactor=redactor)
    return StepLoggingTransport(traced, steps, traced.fully_consumed)


def openai_model(
    model_name: str, base_url: str, transport: httpx2.AsyncBaseTransport, settings: ModelSettings
) -> OpenAIChatModel:
    """A PydanticAI model on an OpenAI-compatible endpoint, every call through `transport`."""
    client = httpx2.AsyncClient(transport=transport)
    provider = OpenAIProvider(base_url=base_url, api_key=PLACEHOLDER_API_KEY, http_client=client)
    return OpenAIChatModel(model_name, provider=provider, settings=settings)
