"""A recorded run on disk: tracefork's tape plus this repo's record beside it (ADR-003).

Each run is a folder `<runs_dir>/<run_id>/` holding `tape.db` (tracefork's
format, untouched) and `record.json` (who ran what, the step order, the
checker's verdict, versions). Runs live in the git-ignored `runs/` folder
and are written readable by the owner only (threat T12).
"""

import os
import uuid
from importlib.metadata import version
from pathlib import Path

from pydantic import BaseModel
from tracefork import Tape

from afr.agents.contract import RunOutcome
from afr.seams.steps import Step

TAPE_FILE = "tape.db"
RECORD_FILE = "record.json"
OWNER_ONLY = 0o600


class RunRecord(BaseModel):
    run_id: str
    agent: str
    agent_version: str
    task_id: str
    # The model name is part of every request body, so replay must reuse it.
    model: str
    steps: list[Step]
    outcome: RunOutcome
    tape_digest: str
    afr_version: str
    tracefork_version: str


def new_run_id(agent: str, task_id: str) -> str:
    return f"{agent}-{task_id}-{uuid.uuid4().hex[:8]}"


def package_versions() -> tuple[str, str]:
    """(agent-bisect, tracefork): stamped on every record so a number traces to its code."""
    return version("agent-bisect"), version("tracefork")


def save_run(runs_dir: Path, record: RunRecord, tape: Tape) -> Path:
    run_dir = runs_dir / record.run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    tape_path = run_dir / TAPE_FILE
    tape.save(str(tape_path))
    record_path = run_dir / RECORD_FILE
    record_path.write_text(record.model_dump_json(indent=2))
    for path in (tape_path, record_path):
        os.chmod(path, OWNER_ONLY)
    return run_dir


def load_run(run_dir: Path) -> tuple[RunRecord, Tape]:
    record = RunRecord.model_validate_json((run_dir / RECORD_FILE).read_text())
    return record, Tape.load(str(run_dir / TAPE_FILE))
