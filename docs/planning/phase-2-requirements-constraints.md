# Phase 2: Requirements & Constraints

Phases 3 (threats) and 4 (design) are folded in, as in Projects 9, 12 and
15. The threat model is the last section of this page: recorded runs are
the most sensitive data any of Arthur's projects hold (prompts, people's
messages, tool results from databases, sometimes keys).

The numbers that prove each requirement are in the
[measurement plan](measurement-plan.md); the build order is in the
[slice plan](slice-plan.md). Record, replay, fork and blame come from
**tracefork** (Phase 5, ADR-001); this page says what this repo adds and
what it needs from tracefork.

## Words used here

| Word | Meaning |
|---|---|
| **Run** | One execution of an agent on one input, from start to final answer |
| **Step** | One model call or one tool call inside a run, in order |
| **Tape** | tracefork's recording of a run: every step's exact request and response, plus the clock, id and random draws the agent read |
| **Replay** | Re-running the agent's code with every response served from the tape; tracefork checks each request by hash |
| **Pin** | Serve a step from the tape instead of calling the model or tool |
| **Fork** | A new run that pins a parent run's first `k` steps, changes step `k`, then continues live |
| **Checker** | Code that says whether a run failed (a Flight School rule, an assertion, a harness grader) |
| **Probe** | Pin `k` steps of a failing run, continue live `S` times, count failures |
| **Decisive step** | The step whose inclusion turns a prefix that usually passes into one that usually fails (measurement plan) |
| **Incident** | A failing run saved as a regression test, with its checker and decisive step |

## Core scenarios

### 1. Recording an agent

1. An agent is described once: an adapter module in `afr_agents/` with
   the callable tracefork runs, its model URL (Ollama's
   OpenAI-compatible endpoint) and its MCP URL (through mcp-gateway).
2. `afr record <agent> --task <id>` runs it through tracefork: model calls
   are taped at tracefork's seam; MCP tool calls are taped by tracefork's
   MCP support or by the gateway hook (ADR-005, spike 1). The gateway's
   detector verdict is attached to each tool step.
3. Before anything is written: secrets are stripped (headers, key
   patterns, Juku's per-call `_meta` delegation token), and, if the run
   isn't synthetic, content is redacted (ADR-009).
4. tracefork's OTel export sends `gen_ai.*` spans to Project 6's Jaeger.

### 2. Building the planted-fault set

1. `afr bench tasks` runs each candidate task 5 times from scratch and
   keeps those with `f(0) ≤ 0.2`.
2. `afr bench plant` records one clean run per kept task, plants each
   fault from the frozen fault plan at its step (a tracefork fork with the
   changed response), continues live, and runs the two effectiveness
   probes.
3. The kept runs, the plan and the seeds are fingerprinted and frozen
   before any method is scored.

### 3. Auto-bisect

1. `afr bisect <run> --check <checker> --max-calls 300` on a failing run.
2. It probes prefixes through tracefork's fork machinery: pin `k`,
   continue live `S` times, run the checker on each continuation.
3. Binary search for the decisive step; each probe's continuations stay as
   forks on the tape, so the evidence can be opened.
4. Output: the decisive step (or a range), `f` on each side, the probes,
   and the cost. It stops with a partial answer when the budget runs out.

### 4. Scoring the methods

1. `afr bench score --method AB|E|B0…B4` runs one method over the frozen
   set and writes a run record; a second scoring of the same method
   version is refused (as in mcp-gateway's `score.py`).
2. `afr bench report` regenerates `docs/results.md` from the records.

### 5. Saving an incident as a test

1. `afr incident save <run> --check <checker>`, with the bisect result if
   there is one.
2. It shows what will be exported (redacted, secret-scanned) and asks to
   confirm before writing into a repo (T9).
3. Out come: the tape and a hash file for `tracefork verify` in CI; a task
   for agent-eval-harness's `regressions` suite; optionally a Flight
   School scenario; and a live-check Inspect task for releases (ADR-008).

### 6. Stepping through an incident (demo page)

1. The demo's incident page shows the bad answer, the probe chart (`f` for
   each `k` probed, the decisive step marked), the fork that fixes it side
   by side with the original, and the saved test.
2. "Open the full tape" opens tracefork's report.

### 7. The live demo

1. Shiori runs on the server through tracefork and the gateway, on
   scripted synthetic conversations with planted tool faults.
2. Curated incidents are published; visitors browse and replay but don't
   type into the recorded agent (ADR-011).

## Functional requirements

MoSCoW. Each Must has a test or a measurement. "tracefork" means the
requirement is met by the dependency and only checked here.

| # | Requirement | Priority | Where |
|---|---|---|---|
| F1 | Record model calls (OpenAI-compatible, streamed and not, with tool calls) | Must | tracefork; checked by spike 1 |
| F2 | Record MCP tool calls through the gateway, with the detector's verdict per step | Must | tracefork's MCP support or the gateway hook (ADR-005) |
| F3 | Bit-exact replay, offline | Must | tracefork; measured on our agents |
| F4 | Fork at a step with a changed model response or tool result | Must | tracefork |
| F5 | Fork with a changed model or system prompt from step `k` | Should | tracefork if supported, else a small adapter option |
| F6 | Agent adapters for A1 and Shiori; A3 (LangGraph) | Must; Should | this repo |
| F7 | Planted-fault set: task filter, fault planter (F1–F5), effectiveness probes, freeze and fingerprint | Must | this repo |
| F8 | Prefix bisection as a tracefork blame strategy, with budget and sequential samples | Must | this repo |
| F9 | Judge baselines B2–B4 as Inspect tasks; B0, B1 | Must | this repo |
| F10 | Score-once runner, run records, `docs/results.md` from records | Must | this repo |
| F11 | Incident save: CI `verify`, harness export, live check | Must (CI, harness); Should (live check) | this repo |
| F12 | Flight School scenario export | Could | this repo |
| F13 | Secret stripping always; Project 15's redaction as a tracefork plugin for non-synthetic runs | Must (secrets, direct identifiers); Should (names, addresses) | this repo, Project 15 |
| F14 | Demo incident page (Vue) and its small API | Must (read-only) | this repo |
| F15 | Meaning-level diff of final answers | Could | this repo, offered upstream |
| F16 | Retention for tapes on the server | Must | tracefork's `prune` plus a schedule |
| F17 | OTel spans to Project 6 | Should | tracefork's export |

## Non-functional requirements

| # | Requirement |
|---|---|
| N1 | **Framework-agnostic in practice:** at least two agents built differently are recorded and replayed with no change to their code (A1, Shiori; A3 if built) |
| N2 | **Light:** on the server, one Python process for the demo API plus Shiori's own; no ClickHouse, Redis or object store; under 250 MB RAM for this repo's parts |
| N3 | **$0:** local models for every measured run; hosted only with Arthur's OK and a cap |
| N4 | **Arthur's stack:** Python (Typer, FastAPI, Pydantic, pytest, uv, ruff, pyright), Vue 3 + TypeScript + Tailwind + Vite + Vitest, Inspect AI, OpenTelemetry via tracefork |
| N5 | **Lean:** the folder's size limits and complexity rules in CI from slice 0; this repo holds only the benchmark, bisect, integrations and demo |
| N6 | **Readable:** `docs/guide.md` follows one planted-fault run from recording, through bisect, to a saved incident |
| N7 | **Public repo:** no server addresses, no October 2026 server-incident details, no employer or client names, no recordings of real people |
| N8 | **Pinned dependency:** tracefork pinned by version and hash; every tracefork function used is read, and bugs found go upstream with a repro |

## Known limits (stated in the README)

- **Only what crosses a seam is taped:** model calls, MCP tool calls, and
  what tracefork captures (clock, ids, random draws). In-process tools that
  aren't MCP, and threads racing, can still make replay fail; tracefork's
  check reports it.
- **Pinned prefixes with a changed prompt are a counterfactual, not a
  re-run:** the recorded responses answered a different request.
- **Live continuations vary:** that's the point of probes, and why each
  is sampled `S` times.
- **Bisection assumes failure is locked in at one step.** Runs that need
  two faults, or where the agent recovers and fails again, show up as
  inconclusive or as monotonicity violations, and are counted.
- **Planted faults are not wild faults.** The headline is about planted
  faults on synthetic tasks with one 4B model.
- **Content-redacted tapes don't replay** (tracefork's rule): real-use
  incidents are for reading; replayable incidents come from synthetic
  runs.

## Constraints

| Constraint | Effect |
|---|---|
| Build starts after Nov 27 | Planning only now; spikes are tiny and wait for a quiet Mac |
| 2–3 weeks of building | The slice plan has a cut list and a marked minimum |
| $0 | Local models; the benchmark is sized to a few nights on the Mac |
| No downloads without asking | Models already on disk (`qwen3.5:4b`, `qwen3:1.7b`); tracefork is a PyPI package, installed only in spike 1, with Arthur's OK (D2) |
| Disk: about 8 GB free on the Mac | Tapes are zstd-compressed; benchmark keeps run records and prunes raw continuations after scoring; budget under 1 GB |
| Heavy jobs one at a time | Benchmark nights never overlap another heavy job |
| Small shared server | Demo API only; tapes with retention |
| tracefork's CI is Linux only | Spike 1 runs it on the Mac; the server is Linux anyway |
| Arthur creates GitHub repos | Push only after the repo exists |

---

## Threat model

### What is worth protecting

| Asset | Why it matters |
|---|---|
| **People's messages** in tapes | Personal data (Indonesia's UU PDP applies to Juku's learners) |
| **Tool results** | Learners' progress and mistakes (Juku), rows from databases (MCP-backbone) |
| **Keys and tokens** | Model API keys in headers; Juku's single-use delegation tokens in `_meta`; keys passed as tool arguments by careless agents |
| **System prompts and agent config** | The agent owner's work |
| **The model budget** | Probes and forks spend real calls if pointed at a paid model |
| **Incident tests** | If they can be edited to pass, the gate is worthless |
| **Systems reached by tools** | A replay or fork must not change real data |
| **The benchmark's integrity** | A set tuned after seeing results makes the headline false |

### Who could cause harm

- A **demo visitor**, curious or hostile.
- **Content inside a tape:** a tool result carrying a prompt injection, or
  model output carrying HTML or script.
- **Arthur by accident:** committing a tape, forking against a live write
  tool, leaving an endpoint open.
- **The dependency:** a bug or a malicious release of tracefork.
- **Someone on the server** with access to another service's files.

### Threats and what's done

| # | Threat | Mitigation | Checked by |
|---|---|---|---|
| T1 | **Keys taped:** an `Authorization` header, a `_meta` delegation token or a key in a tool argument lands in a tape, export or span | Strip before writing: header allowlist, `_meta` credential keys, gitleaks patterns on bodies; the same rule in matching, so replay doesn't diverge on fresh tokens | Canary test (measurement plan): 0 secrets anywhere; gitleaks in CI |
| T2 | **Visitors' personal data** recorded or shown | Visitors don't type into the recorded agent; demo tapes are synthetic; the demo API serves curated incidents only | API tests; the demo's input path doesn't exist |
| T3 | **A fork or probe causes real side effects** | Probes and forks run against fake worlds (Flight School's shop, a Juku test database), never production tool servers; in config, a forked run's MCP URL must point at a server marked sandbox, or the fork refuses to start; tools not marked `readOnlyHint` are refused live outside sandboxes | Test with a fake destructive tool: 0 live calls outside a sandbox |
| T4 | **A taped injection steers a live continuation** | Continuations go through mcp-gateway like the original, so the detector sees results again; the incident page marks steps the detector flagged | Fault F3 runs show the detector's verdicts |
| T5 | **Budget drain or an open relay** | Every probe and fork has a call budget; paid upstreams need an explicit flag and a spend cap; the demo has no live model path for visitors; local endpoints bind to 127.0.0.1 (tracefork's `serve` already does) | Tests for budgets; Project 8 alerts on call-rate spikes |
| T6 | **Incidents edited to pass** | tracefork's content-addressed tapes and hash-checked replay; the incident file stores the tape digest, and CI refuses a mismatch | Test: one changed byte fails CI |
| T7 | **Script in taped content runs in the UI** | Recorded text rendered as text, never with `v-html`; a strict Content-Security-Policy; tracefork's report checked for the same before it's linked publicly | Vitest with a payload set (script tags, `javascript:` links, SVG); the same payloads opened in tracefork's report |
| T8 | **Storage exhaustion** | Size caps per tape; `prune` on a schedule; Project 8's disk alarm | Tests for caps |
| T9 | **A tape committed to the public repo** | `recordings/` ignored; only `afr incident save` writes into a repo, after redaction, a scan and a confirmation; CI scans committed tapes for secrets and canary patterns | `git check-ignore` test; CI scan |
| T10 | **The benchmark tuned to the test set** | Frozen set fingerprinted before method code; score-once per method version; misses become dev cases, never edits to the frozen set | The runner refuses a second score; fingerprints in run records |
| T11 | **A bad tracefork release** | Pinned by version and hash; upgrades are a reviewed commit; the code paths used are read once (CLAUDE.md); tapes are a documented zstd + JSON envelope, never pickle | Lock file in review; the replay-holds check re-run on upgrade |
| T12 | **The tape store read by another service** on the server | Its own user and directory, file mode 600, no network listener for the store | Deployment checklist |

### What's out of scope

- Protecting tapes from Arthur himself on his own Mac (raw tapes are
  allowed there, in the ignored `recordings/` folder).
- Hardening Ollama, the gateway or the MCP servers themselves.
- Use by anyone other than Arthur and demo visitors.
