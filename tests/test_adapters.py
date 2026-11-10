"""The adapter contract's lifecycle: what an adapter starts is always stopped."""

import asyncio
import shutil
from pathlib import Path

import pytest

from afr.agents import get_adapter, then_close
from afr.agents.shop import WORLD_DIR, ShopAgent


class CountingShop(ShopAgent):
    closed = 0

    async def close(self) -> None:
        self.closed += 1


async def failing_work() -> None:
    raise RuntimeError("the run broke")


def test_an_adapter_is_closed_even_when_its_work_fails() -> None:
    adapter = CountingShop()

    with pytest.raises(RuntimeError):
        asyncio.run(then_close(adapter, failing_work()))

    assert adapter.closed == 1


def test_an_unknown_agent_name_lists_the_agents() -> None:
    with pytest.raises(KeyError, match="a1 \\(shop\\), a2 \\(Shiori\\)"):
        get_adapter("a9")


def test_a_task_defined_in_both_task_files_is_refused(tmp_path: Path) -> None:
    shutil.copytree(WORLD_DIR, tmp_path / "world")
    copied = (tmp_path / "world" / "scenarios.yaml").read_text()
    (tmp_path / "world" / "tasks.yaml").write_text(copied)

    with pytest.raises(ValueError, match="defined twice"):
        ShopAgent(tmp_path / "world")
