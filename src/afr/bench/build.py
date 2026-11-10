"""Build a benchmark set for one agent: filter, plant, probe, then hand it to `freeze`.

Long and live (each probe runs the model), so it reports progress as it
goes. Nothing is scored here: the set is built and frozen before any
method runs on it (threat T10).
"""

from collections.abc import Callable

from tracefork import Tape

from afr.agents import AgentAdapter
from afr.bench.effective import Effectiveness, check_fault
from afr.bench.frozen import FrozenSet
from afr.bench.plant import plan_faults
from afr.bench.tasks import TaskVerdict, filter_tasks
from afr.faults import FaultPlan
from afr.recording import ModelConfig, record_run
from afr.runs import RunRecord

Report = Callable[[str], None]
CLEAN_ATTEMPTS = 3  # a kept task passes 4 times in 5, so 3 tries nearly always give a clean run


async def clean_run(
    adapter: AgentAdapter, task_id: str, config: ModelConfig
) -> tuple[RunRecord, Tape] | None:
    """A recorded run of the task that passes, or None after `CLEAN_ATTEMPTS` failures."""
    for _ in range(CLEAN_ATTEMPTS):
        record, tape = await record_run(adapter, task_id, config)
        if not record.outcome.failed:
            return record, tape
    return None


async def build_set(  # noqa: PLR0913 - what bounds a build, each one separate
    adapter: AgentAdapter,
    task_ids: list[str],
    max_tasks: int,
    samples: int,
    config: ModelConfig,
    report: Report,
) -> tuple[FrozenSet, list[tuple[RunRecord, Tape]]]:
    verdicts = await filter_tasks(adapter, task_ids, config, samples)
    report(f"task filter: {sum(v.is_kept for v in verdicts)} of {len(verdicts)} kept")
    plans: list[FaultPlan] = []
    results: list[Effectiveness] = []
    runs: list[tuple[RunRecord, Tape]] = []
    for verdict in kept(verdicts, max_tasks):
        clean = await clean_run(adapter, verdict.task_id, config)
        if clean is None:
            report(f"{verdict.task_id}: no clean run in {CLEAN_ATTEMPTS} tries, skipped")
            continue
        runs.append(clean)
        task_plans = await plan_faults(adapter, clean[0], clean[1], config)
        for plan in task_plans:
            result, bad_run = await check_fault(adapter, clean, plan, samples, config)
            before, after = result.before.failure_rate, result.after.failure_rate
            report(f"{plan.fault_id}: f(k)={before:.1f} f(k+1)={after:.1f}")
            results.append(result)
            if bad_run is not None:
                runs.append(bad_run)
        plans.extend(task_plans)
    frozen = FrozenSet(
        agent=adapter.name, tasks=verdicts, plans=plans, effectiveness=results, tape_digests={}
    )
    return frozen, runs


def kept(verdicts: list[TaskVerdict], max_tasks: int) -> list[TaskVerdict]:
    return [verdict for verdict in verdicts if verdict.is_kept][:max_tasks]
