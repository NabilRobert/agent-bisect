"""The "replay holds" and "nothing missed at the seams" checks (measurement plan).

Records `runs` live runs of one agent, cycling through its tasks, then
replays each with no network. Reports how many replayed bit-exactly with
the same verdict, and compares the calls on the tapes with the calls the
other side logged on its own: Ollama's server log for model calls, the
tool side's log (`RunOutcome.tool_calls_logged`) for tool calls.
"""

from pathlib import Path

from pydantic import BaseModel

from afr.agents import AgentAdapter
from afr.recording import ModelConfig, record_run, replay_run
from afr.runs import save_run

# One line per request in Ollama's server log, e.g.
# [GIN] 2026/11/10 - 16:55:42 | 200 | 2.95s | 127.0.0.1 | POST "/v1/chat/completions"
OLLAMA_CHAT_REQUEST = '"/v1/chat/completions"'


class HoldsReport(BaseModel):
    runs: int = 0
    bit_exact: int = 0
    same_verdict: int = 0
    failures: list[str] = []
    model_calls_taped: int = 0
    model_calls_logged: int | None = None  # None when no Ollama log was given
    tool_calls_taped: int = 0
    tool_calls_logged: int = 0


class OllamaLog:
    """Counts the chat requests Ollama logged after a given point."""

    def __init__(self, path: Path | None) -> None:
        self._path = path

    def mark(self) -> int:
        return self._path.stat().st_size if self._path else 0

    def requests_since(self, mark: int) -> int:
        if self._path is None:
            return 0
        with self._path.open("rb") as log:
            log.seek(mark)
            new_lines = log.read().decode(errors="replace").splitlines()
        return sum(OLLAMA_CHAT_REQUEST in line for line in new_lines)


async def check_replay_holds(
    adapter: AgentAdapter, runs: int, runs_dir: Path, ollama_log: Path | None
) -> HoldsReport:
    log = OllamaLog(ollama_log)
    task_ids = adapter.task_ids()
    report = HoldsReport(model_calls_logged=None if ollama_log is None else 0)
    for number in range(runs):
        mark = log.mark()
        record, tape = await record_run(adapter, task_ids[number % len(task_ids)], ModelConfig())
        logged = log.requests_since(mark)
        save_run(runs_dir, record, tape)
        result = await replay_run(adapter, record, tape)
        report.runs += 1
        report.bit_exact += result.bit_exact
        report.same_verdict += result.same_outcome
        if not (result.bit_exact and result.same_outcome):
            report.failures.append(f"{record.run_id}: {result.divergence or 'verdict changed'}")
        report.model_calls_taped += len(tape.exchanges)
        if report.model_calls_logged is not None:
            report.model_calls_logged += logged
        report.tool_calls_taped += sum(step.kind == "tool" for step in record.steps)
        report.tool_calls_logged += record.outcome.tool_calls_logged
    return report
