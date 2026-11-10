# Guide

A plain-English walk through agent-bisect, kept in step with the code.
Slices 0 and 1 are built: the agents can be recorded and replayed. Planting
faults, bisecting and scoring come next.

## The flow: record a run, then replay it

`afr record a1 --task refund-own-order` runs the shop agent once, live, and
tapes it. Step by step:

1. **The command** (`src/afr/cli.py: record`) looks up the agent's adapter
   (`src/afr/agents/__init__.py: get_adapter`) and calls `record_run`.
2. **The seams are built** (`src/afr/recording.py: build_seams`): an empty
   tracefork `Tape`, a `StepLog`, the secret stripper, and a PydanticAI
   model whose HTTP client is tracefork's recording transport
   (`src/afr/seams/model.py: model_transport`, `openai_model`).
3. **The adapter runs the task** (`src/afr/agents/shop.py: ShopAgent.run`):
   it makes a fresh copy of Flight School's fake shop, serves its tools over
   MCP (`tools_url`), and builds the agent with a taped toolset
   (`src/afr/agents/contract.py: Seams.toolset`).
4. **Each turn** (`shop.py: converse`) sends the scripted customer's next
   line to the agent. Every model call passes through tracefork's transport,
   which stores the request and response bytes and notes a `model` step.
   Every tool call passes through `src/afr/seams/tools.py:
   TapedMCPToolset.direct_call_tool`, which checks the sandbox rule, calls
   the tool, and stores a JSON-RPC frame (a `tool` step). The tool list is
   taped once (a `tools_list` step).
5. **The checker judges the run** (`ShopAgent._judge`): Flight School's rule
   checker reads the shop's own call log, and the shop's data is compared
   with what the scenario expects. Any critical rule or a data mismatch
   means the run failed.
6. **The run is saved** (`src/afr/runs.py: save_run`) as
   `runs/<run_id>/tape.db` (tracefork's format) and `record.json` (the step
   order, the verdict, the model name, versions), readable by the owner only.

`afr replay runs/<run_id>` runs the same adapter with both seams in replay
mode (`recording.py: replay_run`): no model server, no tool server.
tracefork checks every model request's hash; the toolset serves each tool
frame and applies the call to the in-process shop, so the checker sees the
same shop log. The replay passes only if every taped exchange is used, the
step order matches and the verdict is the same.

`afr replay-holds a1 --runs 50` (`src/afr/replay_holds.py`) does that for
many runs and also counts calls the other side logged on its own (Ollama's
server log, the shop's call log) against the tapes: nothing may be missing.

```mermaid
flowchart LR
    CLI[afr record] --> R[recording.record_run]
    R --> S[build_seams: Tape, StepLog, redactor]
    S --> A[ShopAgent.run]
    A -->|model call| M[tracefork transport] --> O[(Ollama)]
    A -->|tool call| T[TapedMCPToolset] --> F[(Flight School shop over MCP)]
    A --> J[checker: rules + expected data]
    J --> D[runs/run_id: tape.db + record.json]
```

## Recording Shiori (A2, local only)

Shiori is Juku's chat agent. juku-agents is a private repo, so A2 runs in
its own local environment and never in CI. The plan is the Juku session's
(P6): Juku's own throwaway test stack, with no change to Juku.

1. A juku-agents checkout pinned to `d939c4f`, outside this repo (Juku's
   test stack reads its migrations, rules and fixtures from the checkout).
2. The environment, with Juku's packages installed editable:

   ```bash
   uv venv -p 3.12 .venv-shiori
   J=<the checkout>
   VIRTUAL_ENV=.venv-shiori uv pip install -e . -e $J/app -e $J/packages/juku-common \
     -e $J/packages/juku-data -e $J/packages/juku-mcp -e $J/packages/juku-testkit -e $J/packages/juku-ops
   ```

3. A throwaway Postgres 16 on its own port, and Juku's settings:

   ```bash
   docker run -d --rm --name afr-juku-test-db --memory 512m -p 127.0.0.1:55460:5432 \
     -e POSTGRES_HOST_AUTH_METHOD=trust postgres:16
   export AFR_JUKU_CHECKOUT=$J JUKU_TEST_ADMIN_URL=postgresql://postgres@127.0.0.1:55460/postgres
   export JUKU_OPENJLPT_DIR=<an OpenJLPT bf4e1ee folder>
   ```

4. `.venv-shiori/bin/afr record a2 --task c01`, then `afr replay` as for A1.

How it works (`src/afr/agents/shiori.py`): the first run starts Juku's
test stack (two throwaway databases and Juku's MCP server in this
process). Each run loads a fresh copy of the task's learner, builds Shiori
with Juku's `build_shiori` on the taped model and a taped toolset that
keeps Juku's `mint_and_record` hook, and asks the question through Juku's
`ask`. The clock is held at the suite's fixture time. Juku's graders
(`answer_match`, `required_tools`) judge the answer. A replay still needs
the stack, because Juku writes chat and budget rows, but makes no model or
MCP call.

## Glossary

| Word | Meaning | Where |
|---|---|---|
| **tracefork** | The library this repo builds on: it records an agent's calls to a tape, replays them exactly, and forks a run at a step | dependency, pinned in `pyproject.toml` |
| **Tape** | tracefork's recording of one run: each model request and response, and each tool frame, byte for byte | tracefork; saved as `tape.db` |
| **Seam** | The place a run touches the outside world, where calls are taped: the model's HTTP client, the MCP toolset | `src/afr/seams/` |
| **Step** | One model call, tool call or tool listing, in the order it happened. tracefork numbers model and tool exchanges separately; `StepLog` keeps one order | `src/afr/seams/steps.py` |
| **Frame** | One JSON-RPC message of a tool call (request or result), as tracefork stores it | `src/afr/seams/tools.py` |
| **Replay** | Running the agent again with every answer served from the tape; any request the tape doesn't hold is an error | `src/afr/recording.py: replay_run` |
| **Bit-exact** | Every replayed request matches the recorded one by hash, and every taped exchange is used | `ReplayResult.bit_exact` |
| **Adapter** | The small module that knows one agent: its tasks, how to build it on the seams, and its checker | `src/afr/agents/` |
| **Checker** | Code that says whether a run failed; for A1, Flight School's rules plus the expected shop data | `ShopAgent._judge` |
| **A1** | The shop agent: PydanticAI in Flight School's fake shop | `src/afr/agents/shop.py` |
| **A2, Shiori** | Juku's chat agent, run on Juku's throwaway test stack; local only | `src/afr/agents/shiori.py` |
| **Sandbox** | A tool server that holds only fake data; outside one, only tools marked read-only may run live (threat T3) | `src/afr/seams/sandbox.py` |
| **`_meta` token** | The single-use delegation token Juku adds to each MCP call; sent to the server, never taped | `src/afr/seams/tools.py` |
| **Redactor** | tracefork's secret stripper, set up with key patterns; applied to what is stored and to what is matched | `src/afr/seams/secrets.py` |
| **Public-repo check** | A script that fails the build on server addresses, private notes, recordings or denylisted names | `scripts/check_public.py` |

## Where to change things

- **Add an agent:** a module in `src/afr/agents/` with a class that has
  `name`, `version`, `task_ids()` and `async run(task_id, seams)`; build the
  agent on `seams.model` and `seams.toolset(...)`, and register it in
  `get_adapter`.
- **Change A1's world, rules or tasks:** `src/afr/agents/shop_world/*.yaml`
  (copied from Flight School; keep the header saying where from).
- **Catch another secret format:** add a pattern to `SECRET_PATTERNS` in
  `src/afr/seams/secrets.py`, with a canary test.
- **Change the model or its address:** `DEFAULT_MODEL` and
  `DEFAULT_MODEL_URL` in `src/afr/recording.py`; the sampling settings are
  `MODEL_SETTINGS` in the agent's module.
- **Add a command:** a function with `@app.command` in `src/afr/cli.py`
  that calls into the package; test the package function, not the CLI.
- **Add a word the public repo must never contain:** append its SHA-256
  (`printf %s word | shasum -a 256`) to `scripts/public_denylist.sha256`.
- **Upgrade tracefork:** change the pin in `pyproject.toml`, run
  `uv lock`, and re-run `afr replay-holds` (threat T11).
