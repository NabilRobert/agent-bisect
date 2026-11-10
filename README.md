# agent-bisect

When an agent run fails, which step broke it? agent-bisect re-runs the
agent from points inside the bad run, keeping the start and resampling the
rest, to find the step after which failure is locked in, the way
`git bisect` finds the commit that broke a build. Then it **measures** how
well that works on live agents, against LLM judges reading the same run
and against checking every step, with the cost of each.

Recording, bit-exact replay and forking come from
[tracefork](https://github.com/pratik916/tracefork) (MIT), pinned. This
repo adds the agents' adapters, a frozen planted-fault benchmark, prefix
bisection, and the wiring into the author's other projects (an MCP
security gateway, an eval harness, a simulated-customer release gate).

## Status

Building. Spikes 1–4 are done (findings in the
[architecture decisions](docs/planning/phase-5-architecture-decisions.md)):
tracefork records and replays a PydanticAI agent on a local model with
MCP tools bit-exactly, and three tracefork bugs were found on the way.
No results yet; the headline numbers will be published whatever they turn
out to be ([measurement plan](docs/planning/measurement-plan.md)).

Everything runs at $0: local models through Ollama, synthetic tasks.

## Run it

```bash
uv sync
uv run afr versions
make check   # lint, types, tests, secrets, public-repo check: what CI runs
```

## Layout

| Path | What it holds |
|---|---|
| `src/afr/cli.py` | The `afr` command; each command calls into the package |
| `tests/` | Tests, written as specifications; no model, no network |
| `scripts/check_public.py` | The public-repo check (no server addresses, private notes, recordings or denylisted names) |
| `docs/guide.md` | The plain-English guide: one run, step by step, and a glossary |
| `docs/planning/` | Problem brief, requirements and threats, measurement plan, decisions, slice plan |

## Licence

MIT, like tracefork.
