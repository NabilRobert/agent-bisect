"""The agents under test, each behind the same small adapter contract (ADR-006).

An adapter knows its tasks, builds its agent on the model and toolsets the
`Seams` hand it, runs one task and judges the result with its own checker.
It never touches tracefork directly, so the same adapter is recorded,
replayed and (later) probed without changes.
"""

from collections.abc import Awaitable
from typing import Protocol

from pydantic_ai.settings import ModelSettings

from afr.agents.contract import RunOutcome, Seams


class AgentAdapter(Protocol):
    name: str
    version: str
    # Set on the model itself, so they apply even when the agent's own code
    # builds the `Agent` (Shiori).
    model_settings: ModelSettings

    def task_ids(self) -> list[str]: ...

    async def run(self, task_id: str, seams: Seams) -> RunOutcome: ...

    async def close(self) -> None:
        """Stop whatever the adapter started for its runs (Shiori's test stack)."""
        ...


def get_adapter(name: str) -> AgentAdapter:
    """The adapter registered under `name`."""
    # Imported here so `afr` starts without loading every agent's dependencies;
    # Shiori's exist only in the local Shiori environment.
    if name == "a1":
        from afr.agents.shop import ShopAgent

        return ShopAgent()
    if name == "a2":
        from afr.agents.shiori import ShioriAgent

        return ShioriAgent()
    raise KeyError(f"no agent {name!r}; the agents are: a1 (shop), a2 (Shiori)")


async def then_close[T](adapter: AgentAdapter, work: Awaitable[T]) -> T:
    """Await `work`, then stop what the adapter started, even if `work` failed."""
    try:
        return await work
    finally:
        await adapter.close()
