"""A2, Shiori: Juku's chat agent, recorded with no change to Juku (P6).

Local only: juku-agents is a private repo, so this runs in `.venv-shiori`
against a pinned checkout named by `AFR_JUKU_CHECKOUT` (setup in
docs/guide.md), never in CI. The plan is the Project 7 session's:
- a throwaway Juku test stack (`evals/eval_stack.py: running_stack`):
  Postgres databases plus Juku's MCP server in this process, no gateway;
- Shiori built by Juku's own code (`build_shiori`, `ask`), on the taped
  model and a taped toolset that keeps Juku's `mint_and_record` hook, so
  every call still carries a fresh `_meta` token that is never taped;
- tasks and graders from Juku's chat suite (`evals/chat/suite.yaml`).

What would make a replay differ, and how it is held still: the clock is
the suite's fixture time (passed to `ask`, and patched into Juku's MCP
server); each run gets a fresh copy of its learner; the token never enters
a frame. Replay still needs the stack (Juku writes chat and budget rows),
but no model and no MCP call.
"""

# Juku's packages exist only in the local Shiori environment; CI type-checks without them.
# pyright: reportMissingImports=false, reportUnknownVariableType=false, reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false

import os
import sys
import uuid
from contextlib import AsyncExitStack
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest import mock

import yaml
from pydantic_ai.settings import ModelSettings
from sqlalchemy import text

from afr.agents.contract import RunOutcome, Seams

JUKU_CHECKOUT_ENV = "AFR_JUKU_CHECKOUT"
CHAT_SUITE = Path("evals") / "chat" / "suite.yaml"
# Juku's own per-call record, written by its `mint_and_record` hook.
TOOLS_CALLED = (
    "SELECT tool FROM monitoring.tool_calls WHERE learner_id = :learner ORDER BY called_at"
)

# As for A1: sampled (probes resample), thinking off. On the model, because
# Juku's code builds Shiori's `Agent` itself.
MODEL_SETTINGS: ModelSettings = {"temperature": 0.7, "extra_body": {"reasoning_effort": "none"}}


def juku_checkout() -> Path:
    value = os.environ.get(JUKU_CHECKOUT_ENV)
    if not value:
        raise RuntimeError(
            f"{JUKU_CHECKOUT_ENV} is not set: point it at a juku-agents checkout pinned to d939c4f "
            "(see docs/guide.md, 'Recording Shiori')"
        )
    return Path(value)


class ShioriAgent:
    """The A2 adapter. One Juku test stack per process, started on the first run."""

    name = "a2"
    version = "1"
    model_settings = MODEL_SETTINGS

    def __init__(self) -> None:
        checkout = juku_checkout()
        # Juku's eval stack is a folder of modules, not a package; its own tests import it this way.
        sys.path.insert(0, str(checkout / "evals"))
        suite = yaml.safe_load((checkout / CHAT_SUITE).read_text(encoding="utf-8"))
        self._now = datetime.fromisoformat(str(suite["fixture"]["now"]))
        self._tasks: dict[str, dict[str, Any]] = {task["id"]: task for task in suite["tasks"]}
        self._exit = AsyncExitStack()
        self._stack: Any = None

    def task_ids(self) -> list[str]:
        return list(self._tasks)

    async def run(self, task_id: str, seams: Seams) -> RunOutcome:
        from juku_app.shiori import mint_and_record
        from juku_testkit.memory_fixtures import load_memory_fixture, source_of

        stack = await self._started_stack()
        task = self._tasks[task_id]
        name = str(task["learner"])
        loaded = await load_memory_fixture(
            stack.db, stack.rules, name, suffix=f"-{uuid.uuid4().hex[:6]}", source=source_of(name)
        )
        toolset = seams.toolset(stack.mcp_url, is_sandbox=True, process_tool_call=mint_and_record)
        answer = await self._ask(stack, seams, toolset, loaded.learner, str(task["prompt"]))
        tools = await tools_called(stack, loaded.learner.id)
        return judge(task, answer, tools)

    async def close(self) -> None:
        await self._exit.aclose()

    async def _started_stack(self) -> Any:
        if self._stack is None:
            from eval_stack import eval_rules, running_stack

            self._stack = await self._exit.enter_async_context(running_stack(eval_rules()))
        return self._stack

    async def _ask(self, stack: Any, seams: Seams, toolset: Any, learner: Any, prompt: str) -> str:
        from eval_stack import AllowAll
        from juku_app.budget import BudgetGuard
        from juku_app.chat import ChatServices, ask
        from juku_app.shiori import build_shiori

        services = ChatServices(
            agent=build_shiori(seams.model, toolset),
            guard=BudgetGuard(stack.db.app, stack.rules),
            moderator=AllowAll(),
            signer=stack.signer,
            app=stack.db.app,
        )
        now = self._now
        with mock.patch("juku_mcp.server.utc_now", lambda: now):
            answer = await ask(services, learner, prompt, now)
        return str(answer.text)


async def tools_called(stack: Any, learner_id: int) -> list[str]:
    async with stack.db.app.connect() as connection:
        rows = await connection.execute(text(TOOLS_CALLED), {"learner": learner_id})
        return [str(row[0]) for row in rows]


def judge(task: dict[str, Any], answer: str, tools: list[str]) -> RunOutcome:
    """Juku's graders for the task (the harness's `answer_match`, `required_tools`)."""
    from eval_records import grade

    graded = grade(task, answer, tools)
    problems = [f"{g['kind']}: {g['spec']}" for g in graded if not g["strict"]]
    return RunOutcome(
        failed=bool(problems), problems=problems, final_answer=answer, tool_calls_logged=len(tools)
    )
