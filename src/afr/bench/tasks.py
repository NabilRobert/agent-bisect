"""The task filter: a task is usable only if the agent passes it from scratch.

A planted fault needs a clean run to break, so each candidate task is run
`samples` times from scratch (a probe pinning nothing) and kept only if at
most `MAX_BASE_FAILURE_RATE` of the runs fail (measurement plan: `f(0) ≤ 0.2`).
"""

from pydantic import BaseModel
from tracefork import Tape

from afr.agents import AgentAdapter
from afr.probing import PinnedRun, probe
from afr.recording import ModelConfig

MAX_BASE_FAILURE_RATE = 0.2
SAMPLES = 5


class TaskVerdict(BaseModel):
    task_id: str
    runs: int
    failures: int

    @property
    def is_kept(self) -> bool:
        return self.failures / self.runs <= MAX_BASE_FAILURE_RATE


def from_scratch(task_id: str, model: str) -> PinnedRun:
    """A run with nothing pinned: probing it at 0 runs the task live."""
    return PinnedRun(tape=Tape(), steps=[], task_id=task_id, model=model)


async def filter_tasks(
    adapter: AgentAdapter, task_ids: list[str], config: ModelConfig, samples: int = SAMPLES
) -> list[TaskVerdict]:
    verdicts: list[TaskVerdict] = []
    for task_id in task_ids:
        result = await probe(adapter, from_scratch(task_id, config.name), 0, samples, config)
        verdicts.append(TaskVerdict(task_id=task_id, runs=samples, failures=result.failures))
    return verdicts
