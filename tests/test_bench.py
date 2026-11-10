"""Building, freezing and loading a benchmark set, end to end with a reactive fake model."""

import asyncio
import json
import shutil
from pathlib import Path

import pytest
from fakes import CarefulShopModel
from tracefork import Tape

from afr.agents.contract import RunOutcome
from afr.agents.shop import ShopAgent
from afr.bench.build import build_set
from afr.bench.effective import first_failing
from afr.bench.frozen import FingerprintMismatch, freeze, load_frozen
from afr.probing import Continuation, LiveRun
from afr.recording import ModelConfig

TASK = "refund-own-order"


@pytest.fixture(scope="module")
def frozen_folder(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One small set (one task, 2 samples per probe), built and frozen once for these tests."""
    config = ModelConfig(name="fake-model", live_transport=CarefulShopModel().transport)
    frozen, runs = asyncio.run(build_set(ShopAgent(), [TASK], 1, 2, config, lambda _: None))
    folder = tmp_path_factory.mktemp("bench") / "a1"
    freeze(folder, frozen, runs)
    return folder


def editable_copy(folder: Path, tmp_path: Path) -> Path:
    copy = tmp_path / "a1"
    shutil.copytree(folder, copy)
    return copy


def test_faults_the_agent_believes_are_effective_and_ones_it_ignores_are_not(
    frozen_folder: Path,
) -> None:
    frozen = load_frozen(frozen_folder)

    effective = {plan.fault for plan, _ in frozen.effective_plans()}
    assert {"F1", "F2"} <= effective  # it believes wrong values and stops on errors
    assert "F3" not in effective  # it ignores instructions in tool results


def test_each_effective_fault_has_a_failing_bad_run_longer_than_its_step(
    frozen_folder: Path,
) -> None:
    frozen = load_frozen(frozen_folder)

    for plan, bad_run_id in frozen.effective_plans():
        record = json.loads((frozen_folder / "runs" / bad_run_id / "record.json").read_text())
        assert record["outcome"]["failed"]
        assert len(record["steps"]) > plan.step


def test_a_manifest_edited_after_freezing_is_refused(frozen_folder: Path, tmp_path: Path) -> None:
    folder = editable_copy(frozen_folder, tmp_path)
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["plans"][0]["step"] += 1
    (folder / "manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(FingerprintMismatch, match="edited"):
        load_frozen(folder)


def test_a_tape_swapped_after_freezing_is_refused(frozen_folder: Path, tmp_path: Path) -> None:
    folder = editable_copy(frozen_folder, tmp_path)
    first, second = sorted((folder / "runs").iterdir())[:2]
    shutil.copy(second / "tape.db", first / "tape.db")

    with pytest.raises(FingerprintMismatch, match="tape"):
        load_frozen(folder)


def live_run(failed: bool, answer: str) -> LiveRun:
    outcome = RunOutcome(failed=failed, problems=[], final_answer=answer, tool_calls_logged=0)
    cost = Continuation(failed=failed, live_model_calls=1, live_tool_calls=0, seconds=0.0)
    return LiveRun(outcome=outcome, tape=Tape(), steps=[], cost=cost)


def test_the_bad_run_is_the_first_continuation_that_failed() -> None:
    runs = [live_run(False, "passed"), live_run(True, "first failure"), live_run(True, "second")]

    chosen = first_failing(runs)

    assert chosen is not None and chosen.outcome.final_answer == "first failure"
    assert first_failing([live_run(False, "passed")]) is None
