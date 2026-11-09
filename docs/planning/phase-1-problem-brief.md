# Phase 1: Problem Brief

**Project:** find the step that broke an agent run, and measure how well
that works. When a recorded run fails, the agent is re-run from different
points of the bad run, keeping the start and resampling the rest, to find
the step after which failure is locked in, the way `git bisect` finds the
commit that broke a build. Failures then become regression tests in the
gates Arthur already runs.

It started as an "agent flight recorder" (record, replay, fork, diff,
bisect, tests, UI). The prior-art search (Phase 5) found recording, exact
replay, forking and per-step counterfactual blame **already built**, in
tracefork (MIT). So this project **builds on tracefork** and puts its
effort where nothing exists yet: **a measurement on live agents**, a
**cheaper search**, and the **wiring** into Arthur's stack.

It is the seventeenth portfolio piece and the **flagship** (D0 in the
slice plan): it uses the gateway, the tracing conventions, the harness,
Flight School, the anonymiser and Juku, around one measured result.
Repo (suggested): `agent-bisect` (D1). Licence: MIT (D7).

**Measurement comes first.** The [measurement plan](measurement-plan.md)
fixes the sets, methods and numbers before any architecture decision.

## Problem

**For people running agents:**
- **A bad agent answer is hard to explain.** A trace shows what happened,
  not which step made it go wrong, and the visible mistake often comes
  several steps after the cause: a wrong tool result at step 3, a wrong
  refund at step 9.
- **The usual answer is to ask a model.** Every observability product
  offers an LLM to read the trace. The research says that works badly at
  the step level: on the Who&When benchmark the best method names the
  right step 14% of the time. Newer benchmarks with planted faults get
  higher, with very large judge models.
- **Re-running from the bad run is the stronger test, but it's costly.**
  Keep the first `k` steps, resample the rest, see if it still fails.
  Doing that for every step costs `n` sets of live runs. Nobody has
  published how well it works on live agents, or how cheap it can be made.
- **Incidents don't become tests.** The failing run sits in a trace store;
  the regression suite is written separately, if at all.

**For the portfolio:**
- Earlier projects **observe** agents (Project 6), **guard** them
  (Project 4) and **test** them before release (Projects 2 and 10). None
  **debugs** a run after the fact.
- Its headline is a **measured claim about a method**, with baselines from
  the literature, not a feature list.
- Choosing to build on tracefork instead of writing a seventh replay tool
  is itself the reuse-first habit an interviewer looks for.

## Users

| Party | Who | Wants |
|---|---|---|
| **An agent developer** | Someone whose agent gave a bad answer | To find the step that broke it, try a fix on that exact run, and keep it as a test |
| **A release owner** | Whoever runs the gates (harness `compare`, Flight School's gate) | Every past incident checked on each release, cheaply |
| **Arthur** | Builder, and the demo's operator | A measured flagship, light enough for the small server, using his other projects |
| **Reviewer / hiring team** | AI and tech people | A clear question, an honest comparison with known tools and papers, numbers with intervals |
| **The tracefork maintainer** | Upstream | Bug reports with repros; a bisect strategy if it earns its place |
| **A demo visitor** | Anyone opening the live demo | To see a bad answer traced to its cause and fixed, in under two minutes |

## Existing tools (summary; details and sources in Phase 5)

| Tool | What it does | Where this differs |
|---|---|---|
| **tracefork** (MIT) | Records at the HTTP seam, bit-exact replay checked by hash, fork any step, per-step blame by flip-rate with intervals, CI `verify`, OTel export, report UI | **The base.** Its blame is validated on scripted fakes only and checks every step; this project measures it on live agents and tests a cheaper search |
| **rewind** (MIT) | Proxy recording, fork and replay with cached prefix, diff, CI baselines; an LLM diagnoses failures | Attribution by an LLM's opinion, not by re-running |
| **retrial** (MIT) | Fork with a patch, `bisect` over resume points | Unmeasured; no cached prefix |
| **Laminar** (Apache-2.0) | Re-runs your script from a step with earlier LLM calls cached | Heavy self-host; LLM calls only; no attribution |
| **LangSmith, Langfuse, Phoenix, Weave, Braintrust, AgentOps** | Traces, one-call playgrounds, datasets from traces | No whole-run replay, no attribution by re-running |
| **LangGraph time travel** | Fork from a checkpoint | LangGraph only; not deterministic |
| **Who&When, Who&When Pro, AgenTracer, A2P** (papers) | Benchmarks and methods where a model reads the log; AgenTracer re-runs only to make training labels | Judges can't re-run; here judges and re-running are scored on the same live runs |

**The angle:** a head-to-head, on live agents with planted faults, of
re-running versus reading, with the cost of each, and a bisection that
tries to keep re-running's accuracy at a fraction of its price.

## Goals and how they're measured

| # | Goal | Target | Measured by |
|---|---|---|---|
| G1 | **Bisection names the step that broke the run** | Beats the best judge protocol on exact-step accuracy (McNemar `p < 0.05`) on the frozen planted-fault set; accuracy target set after the dev set, never lowered | Measurement plan, headline |
| G2 | **It does so cheaply** | ≤ 40% of tracefork's blame in live calls, agreeing with it on ≥ 17 of 20 runs | Measurement plan, headline |
| G3 | **The base holds on our agents** | 100% of clean runs replay bit-exactly, or each failure explained and reported; 0 calls missing | Measurement plan |
| G4 | **Incidents catch their bug** | ≥ 90% of bug/fix pairs: the incident fails on the bug and passes on the fix; CI replay costs $0 | Measurement plan, incidents |
| G5 | **Nothing secret is kept** | 0 secrets anywhere; 0 direct-identifier canaries in redacted exports | Measurement plan, privacy; threat model |
| G6 | **Not tied to one agent** | Two agents written apart (A1, Shiori; A3 if built), unchanged, recorded and scored | Measurement plan |
| G7 | **Light and free** | Under 250 MB RAM for this repo's parts on the server; $0 in models | Cost model |

## Non-goals

- **Another recorder, replayer or trace UI.** tracefork, rewind and the
  observability products do that; this repo depends on one of them.
- **Beating the papers' numbers.** Their judges are far larger and their
  logs can't be re-run; their numbers are quoted for context only.
- **Wild faults.** The headline is on planted faults in synthetic tasks;
  the README says so.
- **Recording real people.** Demo tapes are synthetic; visitors browse.
- **Attribution without a checker.** Bisection needs a way to say "this
  run failed"; checkers come from the harness, Flight School, or the user.
- **Every model API.** OpenAI-compatible first, through tracefork.

## Interfaces

| Provides / needs | With | Form |
|---|---|---|
| Needs: record, replay, fork, blame | tracefork | A pinned dependency; bug reports and a possible PR upstream (D9) |
| Needs, maybe: a tape hook and replay source | mcp-gateway (Project 4) | An interface note to its session, only if spike 1 needs it (ADR-005) |
| Provides: incidents as regression tasks | agent-eval-harness (Project 2) | A `regressions` suite task |
| Provides (Could): incidents as scenarios | AI Flight School (Project 10) | A scenario file |
| Needs: redaction | id-chat-research (Project 15) | Its anonymiser, wrapped as a tracefork plugin |
| Provides: `gen_ai.*` spans | agent-observability (Project 6) | tracefork's OTel export, in Project 6's conventions |
| Needs: the demo agent | Juku (Project 7) | Shiori's base URL and MCP URL set in the demo's deployment; no code change |

## Open questions

Listed with recommendations as D0–D9 in the
[slice plan](slice-plan.md#decisions-for-arthur).
