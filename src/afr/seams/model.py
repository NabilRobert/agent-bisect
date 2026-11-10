"""The model seam: tracefork's transport under PydanticAI's OpenAI client (ADR-004).

tracefork's own PydanticAI adapter fails in both modes on pydantic-ai 2.66
(ADR-001, bugs 1 and 2), so this builds tracefork's `AsyncTraceforkTransport`
directly and hands it to `OpenAIProvider` as its HTTP client: the same seam,
without the adapter's search for the client attribute.
"""

from typing import Literal

import httpx2
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings
from tracefork import Tape
from tracefork.redact import Redactor
from tracefork.transport import AsyncTraceforkTransport

from afr.seams.steps import StepLog

TapeMode = Literal["record", "replay"]

# Ollama ignores the key, but the OpenAI client insists on one.
PLACEHOLDER_API_KEY = "ollama"


class StepLoggingTransport(httpx2.AsyncBaseTransport):
    """Notes each model exchange in the step log once tracefork has handled it."""

    def __init__(self, inner: AsyncTraceforkTransport, steps: StepLog) -> None:
        self._inner = inner
        self._steps = steps

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        response = await self._inner.handle_async_request(request)
        self._steps.add("model")
        return response

    def fully_consumed(self) -> bool:
        return self._inner.fully_consumed()


def model_transport(
    tape: Tape,
    mode: TapeMode,
    steps: StepLog,
    redactor: Redactor,
    live: httpx2.AsyncBaseTransport | None = None,
) -> StepLoggingTransport:
    """Record (through `live`, the real network by default) or replay from `tape`.

    Replay has no inner transport, so a request the tape doesn't hold is an
    error, never a live call (tracefork's contract).
    """
    inner = (live or httpx2.AsyncHTTPTransport()) if mode == "record" else None
    traced = AsyncTraceforkTransport(
        mode, tape, inner, matcher=redactor.matcher(), redactor=redactor
    )
    return StepLoggingTransport(traced, steps)


def openai_model(
    model_name: str, base_url: str, transport: httpx2.AsyncBaseTransport, settings: ModelSettings
) -> OpenAIChatModel:
    """A PydanticAI model on an OpenAI-compatible endpoint, every call through `transport`."""
    client = httpx2.AsyncClient(transport=transport)
    provider = OpenAIProvider(base_url=base_url, api_key=PLACEHOLDER_API_KEY, http_client=client)
    return OpenAIChatModel(model_name, provider=provider, settings=settings)
