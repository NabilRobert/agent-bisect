"""The frozen set on disk, and its fingerprint (threats T6, T10).

`bench/<set>/<agent>/` holds `manifest.json` (the task filter's verdicts,
every fault plan, every effectiveness result) and `runs/` (each clean run
and each bad run, as tracefork tapes plus records). The fingerprint is a
SHA-256 over the manifest's content and every tape's digest. Loading checks
both, so a set that changed after it was frozen is refused, and every
score names the fingerprint of the set it was computed on.
"""

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel
from tracefork import Tape

from afr.bench.effective import Effectiveness
from afr.bench.tasks import TaskVerdict
from afr.faults import FaultPlan
from afr.runs import RunRecord, load_run, save_run

MANIFEST = "manifest.json"
RUNS = "runs"


class FrozenSet(BaseModel):
    agent: str
    tasks: list[TaskVerdict]
    plans: list[FaultPlan]
    effectiveness: list[Effectiveness]
    tape_digests: dict[str, str]  # run id -> tracefork digest
    fingerprint: str = ""

    def effective_plans(self) -> list[tuple[FaultPlan, str]]:
        """(plan, bad run id) for every effective fault."""
        by_id = {plan.fault_id: plan for plan in self.plans}
        return [
            (by_id[result.fault_id], result.bad_run_id)
            for result in self.effectiveness
            if result.is_effective and result.bad_run_id is not None
        ]


class FingerprintMismatch(RuntimeError):
    """The set on disk is not the set that was frozen."""


def compute_fingerprint(frozen: FrozenSet) -> str:
    content = frozen.model_dump(mode="json", exclude={"fingerprint"})
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def freeze(folder: Path, frozen: FrozenSet, runs: list[tuple[RunRecord, Tape]]) -> FrozenSet:
    """Write the set and its runs, stamping the fingerprint."""
    frozen = frozen.model_copy(update={"tape_digests": {r.run_id: t.digest() for r, t in runs}})
    frozen = frozen.model_copy(update={"fingerprint": compute_fingerprint(frozen)})
    for record, tape in runs:
        save_run(folder / RUNS, record, tape)
    (folder / MANIFEST).write_text(frozen.model_dump_json(indent=2))
    return frozen


def load_frozen(folder: Path) -> FrozenSet:
    """The set, after checking its fingerprint and every tape's digest."""
    frozen = FrozenSet.model_validate_json((folder / MANIFEST).read_text())
    if compute_fingerprint(frozen) != frozen.fingerprint:
        raise FingerprintMismatch(f"{folder / MANIFEST} was edited after it was frozen")
    for run_id, digest in frozen.tape_digests.items():
        _, tape = load_run(folder / RUNS / run_id)
        if tape.digest() != digest:
            raise FingerprintMismatch(f"the tape of {run_id} changed after the set was frozen")
    return frozen


def load_frozen_run(folder: Path, run_id: str) -> tuple[RunRecord, Tape]:
    return load_run(folder / RUNS / run_id)
