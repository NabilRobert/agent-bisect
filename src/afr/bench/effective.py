"""Is a planted fault effective? Probes on either side of it (measurement plan).

`before` pins the clean run's first `k` steps (the fault isn't there yet);
`after` pins the planted run's first `k+1` steps (the fault is). A fault is
effective when `f(k) ≤ 0.2` and `f(k+1) ≥ 0.8`: the agent doesn't shrug it
off, and the clean prefix alone doesn't already fail. The first failing
`after` continuation is kept as the fault's "bad run": the run every method
is later asked to explain, with the planted step as the right answer.
"""

from pydantic import BaseModel
from tracefork import Tape

from afr.agents import AgentAdapter
from afr.bench.plant import pinned
from afr.faults import FaultPlan, planted_run
from afr.probing import LiveRun, ProbeResult, continue_and_measure, probe
from afr.recording import ModelConfig, stripped
from afr.runs import RunRecord, package_versions
from afr.seams.secrets import build_redactor

MAX_FAILURE_BEFORE = 0.2  # τ_low
MIN_FAILURE_AFTER = 0.8  # τ_high


class Effectiveness(BaseModel):
    fault_id: str
    before: ProbeResult
    after: ProbeResult
    bad_run_id: str | None

    @property
    def is_effective(self) -> bool:
        return (
            self.before.failure_rate <= MAX_FAILURE_BEFORE
            and self.after.failure_rate >= MIN_FAILURE_AFTER
            and self.bad_run_id is not None
        )


async def check_fault(
    adapter: AgentAdapter,
    clean: tuple[RunRecord, Tape],
    plan: FaultPlan,
    samples: int,
    config: ModelConfig,
) -> tuple[Effectiveness, tuple[RunRecord, Tape] | None]:
    """Both probes for one fault; the bad run comes back too when there is one."""
    record, tape = clean
    clean_run = pinned(record, tape)
    before = await probe(adapter, clean_run, plan.step, samples, config)
    planted = planted_run(clean_run, plan.step, plan.replacement)
    after_runs = [
        await continue_and_measure(adapter, planted, plan.step + 1, config) for _ in range(samples)
    ]
    after = ProbeResult(k=plan.step + 1, continuations=[run.cost for run in after_runs])
    failing = first_failing(after_runs)
    bad_run = None if failing is None else bad_run_record(adapter, plan, record.model, failing)
    effectiveness = Effectiveness(
        fault_id=plan.fault_id,
        before=before,
        after=after,
        bad_run_id=None if bad_run is None else bad_run[0].run_id,
    )
    return effectiveness, bad_run


def first_failing(runs: list[LiveRun]) -> LiveRun | None:
    """The bad run: the first continuation the checker failed."""
    return next((run for run in runs if run.outcome.failed), None)


def bad_run_record(
    adapter: AgentAdapter, plan: FaultPlan, model: str, failing: LiveRun
) -> tuple[RunRecord, Tape]:
    afr_version, tracefork_version = package_versions()
    record = RunRecord(
        run_id=f"{plan.fault_id}-bad",
        agent=adapter.name,
        agent_version=adapter.version,
        task_id=plan.task_id,
        model=model,
        steps=failing.steps,
        outcome=stripped(failing.outcome, build_redactor()),
        tape_digest=failing.tape.digest(),
        afr_version=afr_version,
        tracefork_version=tracefork_version,
    )
    return record, failing.tape
