# Phase 5: Architecture Decisions

Short ADRs, 2026-11-09, written after the
[measurement plan](measurement-plan.md). **All are recommendations until
Arthur settles them.** The ones that need him are marked and listed in the
[slice plan](slice-plan.md#decisions-for-arthur). Licences and prior art
were checked on 2026-11-09; sources are in [Prior art](#prior-art).

**The decision that shapes everything else (ADR-001):** the recording,
exact replay and forking this project set out to build **already exist**,
in tracefork (MIT, 1.0.0). This repo builds on it. Its own work is the
**measurement** (does interventional attribution beat judges on live
agents, and can bisection make it cheap?) plus the **wiring** into
Arthur's stack: mcp-gateway, the harness and Flight School, Project 15's
redaction, and Shiori on the server.

```
         Shiori (PydanticAI)   shop agent A1 (PydanticAI)   LangGraph agent A3
                 │  model calls: tracefork's adapter / proxy (Ollama, OpenAI-compatible)
                 │  tool calls:  MCP → mcp-gateway ─► tape seam (spike 1 decides where)
                 ▼
   ┌───────────────────────────── tracefork (dependency, pinned) ─────────────────────────────┐
   │ tape (zstd, content-addressed, SQLite) · bit-exact replay · fork · blame · diff · report │
   │ redact plugin ◄── Project 15 anonymiser (Indonesian)   · OTel gen_ai export ─► Project 6 │
   └───────────────┬─────────────────────────────┬────────────────────────────┬──────────────┘
                   ▼                             ▼                            ▼
   afr bench: planted faults (frozen),   afr bisect: prefix bisection   afr incident: tape →
   methods AB / E / B0–B4, run records,  (tracefork blame strategy;     harness regressions suite,
   results.md                            offered upstream if it wins)   Flight School scenario, CI verify
                   │
                   ▼
   demo: Vue "incident story" page (bad answer → bisect evidence → fork → diff → saved test)
         + tracefork's own report for the full tape
```

## Reuse map

Arthur's repos were searched first (all of them, excluding employer and
client repos), then everyone else's.

| Part | Reused | Built here (and why) |
|---|---|---|
| Record, bit-exact replay, fork, per-step blame, diff, tape report, OTel export | **tracefork** (MIT) | Nothing; bugs found are reported upstream (CLAUDE.md, "hunt for bugs") |
| MCP interception, detector decisions, audit hash chain | **mcp-gateway** (Project 4): one forwarding point, `_forward` in `proxy.py`; upstreams behind an `Upstreams` protocol | Only if spike 1 shows tracefork can't tape MCP over HTTP: a tape hook, built **in the gateway's repo by its session** (ADR-005) |
| Generic trace view, span conventions | **agent-observability** (Project 6): Jaeger v2, `docs/conventions.md` | Nothing: tracefork's `gen_ai.*` export goes there |
| Shop world, tools, rule checker, seeded bugs | **AI Flight School** (Project 10) | A small model-driven shop agent (A1) for the benchmark |
| Regression gate, suite format | **agent-eval-harness** (Project 2): suite YAML with graders, `compare` | An exporter from incident to a harness task (ADR-008) |
| Response cache for live checks | **Inspect AI**'s model cache, when a live check runs as an Inspect task | — |
| Redaction | **id-chat-research** (Project 15): Presidio-based Indonesian anonymiser (in progress on its branches) | A tracefork redact plugin wrapping it (ADR-009) |
| Demo agent | **Juku**'s Shiori (Project 7): PydanticAI, base URL configurable, tools over MCP through the gateway | Nothing in Juku |
| Judge baselines | Who&When and Who&When Pro's protocols (all-at-once, step-by-step, binary search over the log) | Re-implemented as Inspect tasks from the papers; no data from either dataset is used (licences, ADR-007) |
| Step-level failure attribution by re-running | tracefork's blame (per-step flip-rate scan); retrial's `bisect` (MIT, unmeasured) | **Prefix bisection with a sequential sample rule**, and the measurement: the headline |

## ADR-001: Build on tracefork, not a recorder of our own (needs Arthur, D2)

**Context:** the brief scoped record → replay → fork → diff → bisect →
tests → UI as one product to build. The prior-art search found every one
of those pieces already built, twice over, under MIT:

- **tracefork** (MIT, 1.0.0, Python ≥ 3.12, single author, about 1,600
  offline tests, CI on Linux only): records at the HTTP seam (Anthropic,
  OpenAI, Gemini, Bedrock; a base-URL proxy for other clients), replays
  **bit-exactly, checked by hash**, including clock, id and random draws;
  forks any step; **blame** ranks steps by flip-rate with Wilson intervals,
  budget-capped; `validate` plants faults and checks blame finds them;
  `verify` is a CI gate; redaction, OTel `gen_ai.*` export and ingest, an
  HTML report and a local server UI; adapters for LangGraph, PydanticAI,
  OpenAI Agents SDK, CrewAI, AutoGen, ADK. Its own README says its blame
  numbers come from **scripted fakes, not live models**, and that it has
  never been run on an external benchmark.
- **rewind** (MIT, single binary): proxy recording with streaming, fork
  and replay from step `n` with the prefix from cache, timeline diff,
  sessions as CI baselines, OTel and Langfuse import, and `rewind fix`,
  where an LLM diagnoses the failure (not counterfactual).
- **retrial** (MIT, 0.3.0): records, forks with a JSON patch at step `k`
  (live), `bisect` by binary search over resume points; no measurements.

**Decision:** depend on **tracefork**, pinned by version and hash. This
repo holds the benchmark, the bisect strategy, the integrations and the
demo. Spike 1 (slice plan) is the gate: tracefork must record, replay
bit-exactly and fork Shiori and the shop agent on the Mac, with the model
on Ollama and tools over MCP through the gateway.

**Why:**
- CLAUDE.md: "a hand-written copy of a mature tool isn't" the work. A
  second recorder would be just that.
- tracefork is in Arthur's language and stack (Typer, FastAPI, zstd,
  SQLite), has a plugin API for matchers, oracles and adapters, and blame
  is already the exhaustive scan the measurement needs as a competitor.
- The thing tracefork can't say about itself ("does this work on live
  agents, against judges, at what cost?") is exactly what this project
  measures. That is a better flagship claim than a seventh replay tool.

**Fit check (CLAUDE.md):** licence MIT, fine. Maintained: active (pushed
2026-11-04) but **one person**; mitigated by pinning, reading the code
paths used, and the fallback below. $0. Light: no services. Private: runs
offline.

**Fallback (if spike 1 fails on something tracefork can't fix soon):** a
thin substrate of our own, as first designed: an OpenAI-compatible
FastAPI + httpx proxy with the run id in the URL path, SQLite flight log
with request hashes after redaction, strict replay with divergence
reports, pinned-prefix forks. About 3 extra days, taken from the cut list.

**Rejected:**
- **Our own recorder first** (the original scope): duplicates tracefork
  and rewind, and spends the 2–3 weeks on solved parts.
- **rewind as the base:** single binary, not extendable from Python; its
  attribution is an LLM's diagnosis, not counterfactual.
- **retrial as the base:** younger, smaller, live forks only (no cached
  prefix).
- **Laminar** (Apache-2.0): reruns your script with LLM calls cached up to
  a step, but needs ClickHouse, Quickwit and Postgres, and doesn't say
  tool calls are cached.
- **LangGraph time travel:** LangGraph agents only; the continuation isn't
  deterministic.
- **Langfuse or Phoenix as store and UI:** neither can serve a recorded
  response back, so neither can replay. Langfuse (MIT outside `ee/`) wants
  about six services and a 16 GiB VM; Phoenix is one container but under
  the **Elastic License 2.0**, which bars offering it as a hosted service.
  Both remain fine as *viewers*: Project 6's Jaeger already is one.

## ADR-002: OpenTelemetry is for watching, the tape is for replaying

**Decision:** replay, forks and bisect use tracefork's tape. OTel
`gen_ai.*` spans are exported to Project 6's Jaeger for the generic trace
view and to link a tape to the wider trace (gateway, database spans).

**Why:** spans are a write-only stream: exported in batches, sometimes
sampled, and with message content **off by default** (the GenAI
conventions make `gen_ai.input.messages` and `gen_ai.output.messages`
opt-in, and Project 6's conventions keep content out on purpose). The
GenAI conventions are also still marked **Development** and moved to
their own repo in June 2026. Replay needs exact bytes.

**Rejected:** *spans as the source of truth*; *turning on content capture
in Project 6* (it would put prompts into a store built to keep them out).

## ADR-003: The tape format is tracefork's; our metadata lives beside it

**Decision:** tapes stay in tracefork's format (versioned zstd envelope,
content-addressed, SQLite, no pickle). What this repo adds lives in small
Pydantic sidecar records, keyed by tracefork's run id:
- `AgentSpec`: name, version or git sha, config hash, adapter;
- `FaultPlan`: task, step, fault type, payload, seed (frozen set);
- `ProbeResult`: run, prefix length, samples, failures, calls, tokens,
  seconds;
- `AttributionResult`: method, named step or range, cost;
- `Incident`: tape digest, checker, decisive step, export targets.

Run records are JSONL with a fingerprint, as in the harness.

**Why:** one tape format, owned upstream; the benchmark's own data is
plain and checked.

**Rejected:** *our flight log format* (fallback only, ADR-001); *a
database for the sidecars* (JSONL is enough for hundreds of runs).

## ADR-004: Model calls through tracefork's seams, models on Ollama

**Decision:** the PydanticAI agents (Shiori, A1) are recorded through
tracefork's PydanticAI adapter, or its base-URL proxy if the adapter
doesn't fit (spike 1). The model is `qwen3.5:4b` on Ollama's
OpenAI-compatible endpoint. A3 (LangGraph, Should) uses the LangGraph
adapter.

**Why:** no change to Shiori's code: it already takes a base URL. The
proxy covers anything that isn't Python.

**Watch for:** tracefork was built around Anthropic's SDK and moved to
`httpx2`; PydanticAI's OpenAI client uses `httpx`. Spike 1 checks the
OpenAI path with streaming and tool calls end to end.

## ADR-005: MCP tool calls: tracefork's MCP support first, a gateway hook if needed (needs Arthur, D3)

**Decision:** spike 1 checks whether tracefork tapes MCP tool calls made
over streamable HTTP (its `mcp` extra) for Shiori's `MCPToolset`, so that
replay serves tool results without calling the gateway.
- **If yes:** the gateway's detector decision for each call is added to
  the tape as step metadata, read from the gateway's audit log by call id
  (no gateway change).
- **If no:** ask the Project 4 session for a small, general **tape hook**
  in mcp-gateway: after `_forward` and the detector, hand the full call
  (arguments, result, `isError`, `_meta` without credentials, tool
  annotations, verdict) to a sink, and an `Upstreams` replay source that
  answers from a tape. This repo wraps it as a tracefork plugin.

**Why:** the gateway already sees every tool call of Arthur's agents and
holds the detector. A second MCP proxy here would copy its transport and
`_meta` handling. Its audit log keeps only a hash of each result, by
design, so it can't be the tape.

**Must hold either way:** Juku puts a **single-use delegation token** in
`_meta` on every call. It must be stripped before taping and left out of
request matching, or every replay diverges and the tape holds a
credential (threat model T1).

## ADR-006: The agent contract: a callable, per tracefork

**Decision:** each agent gets a small adapter module in this repo,
`afr_agents/<name>.py`, exposing the `pkg:fn` callable tracefork's
`replay`, `fork` and `blame` take, plus an `AgentSpec`. Inputs come from
the task list.

**Why:** that's tracefork's contract; meeting it costs a few lines per
agent and needs no change in Juku or Flight School.

## ADR-007: Prefix bisection, measured against tracefork's blame and three judges

**Decision:** auto-bisect, as defined in the measurement plan: probe `k`
pins `k` steps and continues live `S` times; binary search for the
decisive step; 5 samples per probe, 10 when undecided, else inconclusive;
a call budget. Built as a **tracefork blame strategy** through its plugin
API, so tracefork's forks and tapes hold the evidence. Offered upstream as
a PR if it meets the pass rules.

Measured against:
- **E: tracefork's blame as shipped** (every step, flip-rate), on the
  20-run subset;
- **B2–B4: judge protocols from Who&When and Who&When Pro** (all at once,
  step by step, binary search over the log), re-implemented as Inspect
  tasks with the local model;
- B0 random, B1 last step.

**Why:** tracefork's scan costs `n` probes per run; bisection costs about
`log2(n)`. Whether it keeps the accuracy, and how both compare with
reading the log, has not been measured on live agents by anyone found
(prior art).

**Datasets not used:** Who&When Pro's data is listed under **CC BY-NC-SA
4.0** and its runs can't be re-executed here anyway; Who&When's logs are
post-hoc only. Their *protocols* are reused, cited, and their published
numbers quoted for context, never compared directly (different task).

**Rejected:** *a judge as the method* (it's the baseline); *delta
debugging over step sets* (needs a passing run of the same input; a later
Could); *Shapley-style credit over interacting steps* (tracefork and
Causal Agent Replay do it; out of scope for 2–3 weeks).

## ADR-008: Incidents become tests in the gates that already exist

**Decision:**
1. **CI, every push, $0:** `tracefork verify` on each saved incident tape
   (bit-exact replay, no model calls), plus this repo's check that the
   checker still flags the recorded failure.
2. **agent-eval-harness:** `afr incident export --harness` writes a task
   into a non-frozen `regressions` suite (prompt from the run; graders
   mapped from the checker: `forbidden_tools`, `answer_excludes`, …),
   gated by the harness's `compare` as usual.
3. **AI Flight School** (Could): a scenario with the run's customer turns
   and the rules that fired.
4. **Live check, per release, budgeted:** pin up to the decisive step,
   continue `S` times with the current agent, as an Inspect task with the
   cache on, so an unchanged agent costs nothing.

**Why:** Projects 2 and 10 own the gates; incidents should feed them.

**Rejected:** *a third gate of our own*; *rewind's session baselines* (a
second tool for the same tapes).

## ADR-009: Redaction: Project 15's anonymiser as a tracefork redact plugin

**Decision:** wrap Project 15's anonymiser (Indonesian phone numbers,
NIK, plates, accounts, emails; names and addresses when its NER stage
lands) as a tracefork redaction plugin, plus secret patterns and the
`_meta` credential rule. tracefork already distinguishes metadata
redaction (still bit-exact) from content redaction (forensic only, can't
replay): this repo follows that rule.
- Benchmark and demo tapes are recorded from **synthetic inputs only**,
  so they need no content redaction and replay exactly.
- Tapes from real use (Arthur's own Juku sessions) are content-redacted
  before they leave the Mac, and are then for reading, not replaying.

**Why:** "redact at record time" and "replay exactly" pull against each
other; tracefork's split is the honest answer. Keeping the demo synthetic
removes the conflict where it matters most.

**Rejected:** *stand-in values to keep redacted tapes replayable* (the
original plan): a replay against changed content isn't the recorded run;
a Could at most. *Encrypting instead of redacting* (the key would sit
beside the data).

## ADR-010: Meaning-level diff: a local judge on claims (Could)

**Decision:** the local model splits each final answer into short claims
and labels each pair: same, different, only in A, only in B. An Inspect
task, measured against Arthur's labels (κ ≥ 0.6 to ship). Offered
upstream to tracefork's `diff` if it passes.

**Why:** none of the tools found diffs answers by meaning; rewind and
LangSmith score runs, they don't say what changed.

**Rejected:** *embeddings* (a download; a score without an explanation);
*a hosted judge* (cost; sends content out).

## ADR-011: The demo: Shiori on the server, curated incidents (needs Arthur, D4, D5)

**Decision:** Shiori runs on the server recorded through tracefork and the
gateway, on **scripted synthetic conversations** (a learner asking about
JLPT words, with planted tool faults). A handful of curated incidents,
each with its bisect evidence, a fixed fork and the saved test, are
published. Visitors browse and replay; they don't type into the recorded
agent, so no visitor data is recorded at all. Live forks: Arthur only.

**Why:** a real agent beats a toy; curated and synthetic keeps strangers'
data out (T2) and the Sumopod budget out of reach (T5).

**Rejected:** *visitors chatting with a recorded Shiori* (their words
would be recorded; redaction then breaks replay, ADR-009); *the Flight
School shop agent* (a toy shop, less telling).

## ADR-012: The UI: a Vue "incident story" page; tracefork's report for the rest

**Decision:** one Vue 3 + TypeScript + Tailwind page per incident, built
for the demo's two minutes: the bad answer → the probe chart (failure rate
after pinning `k` steps, the decisive step marked) → the fork that fixes
it, side by side with the original (jsondiffpatch, MIT, for JSON; `diff`,
BSD-3, for text) → the saved test. It reads exported JSON from a small
FastAPI endpoint. The full tape opens in tracefork's own report.

**Why:** tracefork already has a timeline, step detail, fork tree and
cost view. The story of one incident, especially the probe chart, is what
it doesn't show, and it's what a visitor should see.

**Rejected:** *a full time-travel UI of our own* (rebuilds tracefork's
report); *only tracefork's report* (it doesn't tell the bisect story);
*starting from Pitstop's Vue Run Inspector* (`gads-case-study`, the
closest thing Arthur has built; it has no LICENSE file, and one page
doesn't need it).

## ADR-013: Framework and library choices

| Need | Choice | Rejected |
|---|---|---|
| Record, replay, fork, blame | tracefork (pinned) | own substrate (fallback); rewind; retrial |
| CLI | Typer (`afr`) | — |
| Demo API | FastAPI | — |
| Sidecar records | Pydantic + JSONL | SQLAlchemy (no database needed now) |
| Benchmark agents | PydanticAI (as Juku); LangGraph for A3 | — |
| Judges, live checks, meaning diff | Inspect AI | a custom judge loop |
| Statistics | statsmodels `proportion_confint` (Wilson), `mcnemar` (exact) | hand-rolled intervals |
| Property tests | Hypothesis (MPL-2.0, test only) | — |
| Secret scanning | gitleaks in CI; its patterns in the redact plugin | detect-secrets |
| Tracing | tracefork's OTel export to Project 6 | — |
| Local models | Ollama, models on disk | llama-server (not installed) |
| UI | Vue 3, TypeScript, Tailwind, Vite, Vitest; jsondiffpatch; `diff` | Monaco diff (heavy) |

---

## Prior art

Checked 2026-11-09 from official docs, repos, PyPI and arXiv. Where a
claim couldn't be confirmed it says so.

### Products and tools

| Tool | Licence (self-host) | Footprint | Whole-run replay | Fork from step | Attribution | Trace → test |
|---|---|---|---|---|---|---|
| **LangSmith** | Proprietary; self-host is an Enterprise add-on | ClickHouse, Postgres, Redis, blob store | No: playground re-sends one call | Only through LangGraph Studio | An LLM assistant explains runs | Yes |
| **Langfuse** | MIT outside `ee/` | web, worker, Postgres, ClickHouse, Redis, S3; 16 GiB VM advised | No: "session replay" is visual; one-call playground | No | No | Yes |
| **Arize Phoenix** | Elastic License 2.0 | One container, SQLite or Postgres | No: "span replay" loads one call into the playground | No | No | Datasets |
| **AgentOps** | SDK MIT; dashboard ELv2 | ClickHouse, Supabase, collector | No: a visual timeline. "Time travel" appears only in third-party docs (unconfirmed) | Unconfirmed | No | Unconfirmed |
| **W&B Weave** | SDK Apache-2.0; self-managed in private preview | W&B platform, ClickHouse, S3 | No: one-call playground | No | No | Evaluations |
| **Braintrust** | Proprietary | Enterprise data plane | No: re-runs one eval row | No | No | Yes |
| **Laminar** | Apache-2.0 | Postgres, ClickHouse, Quickwit, … | Partly: re-runs your script, LLM calls cached up to a step (four integrations); tools not stated | Yes | No | Evals in CI |
| **OpenLLMetry** | Apache-2.0 | Instrumentation only | No | No | No | No |
| **Inspect log viewer** | MIT | Local | No (logs, `eval-retry`, a generate cache) | No | No | Logs are evals |
| **LangGraph** | MIT | Your checkpointer | From a checkpoint; tail re-runs live, not deterministic | Yes, LangGraph only | No | No |
| **tracefork** | MIT | None (library, CLI, local UI) | **Yes, bit-exact, hash-checked** | Yes | **Per-step flip-rate blame with intervals; validated on scripted planted faults only** | `verify` CI gate |
| **rewind** | MIT | Single binary | Yes, prefix from cache | Yes | An LLM diagnoses (`rewind fix`) | Session baselines, GitHub Action |
| **retrial** | MIT | SQLite | Fork seeds history, then live | Yes (JSON patch) | `bisect` over resume points; unmeasured | `rerun` |
| **mcp-recorder, agentape** | MIT | Proxy | MCP only (cassettes) | No | No | Cassette tests |
| **vcrpy, pytest-recording** (+ LLM cassette libraries) | MIT | Library | HTTP cassettes, in-process | No | No | Tests |

### Research on finding the failing step

| Work | What it does | Step-level result |
|---|---|---|
| **Who&When** (arXiv 2505.00212) | Benchmark of multi-agent failure logs labelled with the decisive step; judges read the log | Best method **14.2%** (agent-level 53.5%) |
| **Who&When Pro** (arXiv 2607.09996) | 12,326 failed runs made by **replaying a successful run's prefix exactly, then planting an error**, the same mechanic as this plan; judges incl. a binary search over the log | Best **73.9%** on text (Qwen3.5-122B, all at once). Data CC BY-NC-SA 4.0 |
| **AgenTracer** (arXiv 2509.03312, ICLR 2026) | Counterfactual replay and planted faults used to **label training data**; then a trained 8B model reads logs | 20.7% hand-made, 42.9% automated |
| **A2P** (arXiv 2509.10401) | Counterfactual *reasoning* by an LLM, no re-execution | 29.3% hand-made, 47.5% generated |
| **Causal Agent Replay** (arXiv 2606.08275) | `do()` on one step, resample forward, Shapley for interacting steps | Synthetic causal models only |
| **CausalFlow** (arXiv 2605.25338) | Counterfactual responsibility scores per step | No numbers in the abstract |

### What's new here, honestly

**Not new:** recording, exact replay, forking, run diffs, traces to
tests, time-travel views, and per-step counterfactual blame (tracefork).
Bisecting over resume points exists (retrial), unmeasured.

**New, as far as the search found:**
1. **A measurement on live, stochastic agents** of interventional
   attribution (tracefork's blame and prefix bisection) against the judge
   protocols the literature uses, on the same planted-fault runs, with the
   cost of each. tracefork measured on scripted fakes; the papers measure
   judges on logs they can't re-run.
2. **Prefix bisection with a sequential sample rule**, measured for how
   much accuracy it keeps for its `log2(n)` cost.
3. **Gateway-aware tapes:** MCP tool calls with the injection detector's
   decision on each step, so an incident shows whether the gateway saw it.
4. **Incidents feeding existing gates** (the harness's `compare`, Flight
   School) rather than a tool's own baseline.
5. **Indonesian redaction** of tapes, and **a meaning-level diff** of
   answers (Could).

### Sources

Fetched 2026-11-09. Products: LangSmith self-hosting
(docs.langchain.com/langsmith/self-hosted); Langfuse licence and
self-hosting (langfuse.com/docs/open-source, langfuse.com/self-hosting,
…/deployment/docker-compose); Phoenix licence and deployment
(github.com/Arize-ai/phoenix/blob/main/LICENSE,
arize.com/docs/phoenix/self-hosting); Phoenix span replay
(arize.com/docs/phoenix/prompt-engineering/overview-prompts/span-replay);
AgentOps (github.com/AgentOps-AI/agentops, app/LICENSE;
docs.agentops.ai/v2/usage/dashboard-info); Weave
(weave-docs.wandb.ai/guides/platform/weave-self-managed); Braintrust
(braintrust.dev/docs/guides/self-hosting); Laminar
(github.com/lmnr-ai/lmnr, laminar.sh/docs/debugger/caching); OpenLLMetry
(github.com/traceloop/openllmetry); Inspect
(inspect.aisi.org.uk/log-viewer.html); LangGraph time travel
(docs.langchain.com/oss/python/langgraph/use-time-travel); tracefork
(github.com/pratik916/tracefork, README and pyproject.toml read
directly); rewind (github.com/agentoptics/rewind, README read directly);
retrial (pypi.org/project/retrial); mcp-recorder
(github.com/devhelmhq/mcp-recorder); agentape (github.com/matsurih/agentape).
OpenTelemetry GenAI conventions
(github.com/open-telemetry/semantic-conventions-genai: gen-ai-spans.md,
gen-ai-agent-spans.md, mcp.md). Papers: arXiv 2505.00212 (Who&When),
2607.09996 (Who&When Pro), 2509.03312 (AgenTracer), 2509.10401 (A2P),
2606.08275 (Causal Agent Replay), 2605.25338 (CausalFlow).

**Not confirmed:** AgentOps' "time travel debugging" (third-party docs
only); Langfuse's mapping of `gen_ai.input.messages`; Who&When's venue.
tracefork's and rewind's claims are from their READMEs, not from running
them: spike 1 runs tracefork.
