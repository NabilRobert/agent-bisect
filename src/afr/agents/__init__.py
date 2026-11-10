"""The agents under test, each behind the same small adapter contract (ADR-006).

An adapter knows its tasks, builds its agent on the model and toolsets the
`Seams` hand it, runs one task and judges the result with its own checker.
It never touches tracefork directly, so the same adapter is recorded,
replayed and (later) probed without changes.
"""

from typing import Protocol

from afr.agents.contract import RunOutcome, Seams


class AgentAdapter(Protocol):
    name: str
    version: str

    def task_ids(self) -> list[str]: ...

    async def run(self, task_id: str, seams: Seams) -> RunOutcome: ...


def get_adapter(name: str) -> AgentAdapter:
    """The adapter registered under `name`."""
    # Imported here so `afr` starts without loading every agent's dependencies.
    from afr.agents.shop import ShopAgent

    adapters: dict[str, AgentAdapter] = {"a1": ShopAgent()}
    if name not in adapters:
        raise KeyError(f"no agent {name!r}; the agents are: {', '.join(sorted(adapters))}")
    return adapters[name]
