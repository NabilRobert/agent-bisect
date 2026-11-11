# Slice Plan and Cost Model

The build starts after Nov 27 and is sized for **about 15 working days**
(3 weeks), with a marked minimum at about 8. Every slice costs $0: local
models already on the Mac, synthetic inputs.

Building on tracefork (ADR-001) moved about 6 days of recorder work out of
the plan; they went into the benchmark, a third judge protocol, and the
integrations. If spike 1 fails, the fallback (our own thin recorder) takes
about 3 days back from the cut list.

## Prerequisites

| # | Prerequisite | Needed for | Who |
|---|---|---|---|
| P1 | Arthur settles D0–D9 below and OKs the five docs | Spike 1 | Arthur: done 2026-11-10, all as recommended |
| P2 | The GitHub repo `agent-bisect` exists (D1) | Pushing anything | Arthur |
| P3 | If spike 1 finds tracefork can't tape MCP over HTTP: a tape hook and a replay source in mcp-gateway (ADR-005), built **in its repo by its session** | Slice 2 | Project 4 session: **not needed** (spike 1, 2026-11-10: a wrapper on tracefork's tool seam tapes MCP; ADR-005) |
| P4 | Project 15's anonymiser installable as a package (direct identifiers at least) | Slice 7 | Project 15 session |
| P5 | AI Flight School's shop world and tools reachable over MCP from an agent outside its repo; its 7 seeded-bug reference agents importable (`flight_school.reference.agent:refunds_twice`, …) | Slices 1, 4 | Project 10 session (check only): **tools over MCP confirmed** in spike 3 (`running_tool_server`, its `main` at 7f18196) |
| P6 | Shiori runnable one-shot against Ollama's OpenAI-compatible endpoint, with a Juku test database behind its MCP tools. It already takes a `base_url`, so likely a check only | Slices 1, 6 | Project 7 session |
| P7 | Two or three nights of Mac time with no other heavy job | Slice 3c | Arthur (scheduling): **Friday 13 and Saturday 14 November 2026** (decided 2026-11-11) |
| P8 | About 1 hour of Arthur's time to label answer pairs | Slice 9 (Could) | Arthur |

## Spikes (after Nov 27, before slice 0; tiny, $0, on a quiet Mac)

| # | Question | Method | Pass | Time |
|---|---|---|---|---|
| 1 | **The gate:** does tracefork record, replay bit-exactly and fork a PydanticAI agent on the Mac, with the model on Ollama (OpenAI-compatible, streamed, tool calls) and tools over MCP through mcp-gateway? Does `blame` run on it? | Install tracefork in a scratch venv (D2); a 4-step PydanticAI agent with one MCP tool; record, `replay`, `verify`, `fork` at step 2, `blame --k 2` | All pass → ADR-001 stands. MCP not taped → P3. Model path broken → report upstream; if not fixable within days, the fallback | 2 h |
| 2 | Can a blame strategy be added through tracefork's plugin API, without forking the project? | Read `docs/plugin-api.md` and `blame.py` | A named extension point, or a small upstream PR planned | 1 h |
| 3 | Seconds per call and calls per continuation for A1 on `qwen3.5:4b` | Time 5 tasks once | The compute table in the measurement plan updated | 1 h |
| 4 | Is Shiori deterministic apart from model and tool calls? | Read it for clocks, ids, ordering; the `_meta` token is one known source | List written into ADR-005 | 30 min |

Only findings are committed (in the ADRs), never spike code.

## Slices

**Evaluation first:** the frozen planted-fault set (3a) exists before the
bisect code (3b). Each new test is mutation-checked once. Each slice
updates `docs/guide.md`.

| Slice | Delivers | Done when | Days |
|---|---|---|---|
| **0. Scaffold** | uv project, tracefork pinned; `afr` Typer CLI skeleton; README with layout; CI (ruff with complexity rules, pyright strict, pytest, gitleaks, the public-repo check N7); `docs/guide.md` stub | CI green | 0.5 |
| **1. Agents on tape** | The A1 shop agent (PydanticAI over Flight School's world); adapters for A1 and Shiori (ADR-006); secret stripping including `_meta` tokens (T1); sandbox guard (T3) | "Replay holds" on 50 runs per agent: 100% or explained; 0 missing calls; canary secrets test passes; destructive-tool test passes | 2 |
| **2. Gateway on the tape** | Detector verdict per tool step (from the audit log, or the P3 hook) | Fault F3 runs show verdicts; replay still holds | 1 |
| **3a. Planted-fault set** | Task filter; fault planter F1–F5; effectiveness probes; the dev set; freeze and fingerprint | Frozen set committed **before** bisect code; effective-run counts per fault type | 1.5 |
| **3b. Prefix bisection** | The blame strategy (ADR-007): probes, sequential samples, budget, ranges; property tests | Property tests pass on fake agents with known `f(k)`; dev set scored | 1 |
| **3c. Baselines and results** | B0–B4 (judges as Inspect tasks); E (tracefork's blame) on the subset; score-once runner; run records; `docs/results.md` | Frozen set scored once by every method; headline sentence written with its numbers, whatever they are | 1.5 (plus 2–3 nights) |
| **— Minimum that still impresses: spikes + slices 0–3c (about 8 days) —** | | | |
| **4. Incidents become tests** | `afr incident save`; CI `verify` check; harness `regressions` export; live check as an Inspect task with cache | Bug/fix pairs: ≥ 90% behave correctly; CI costs $0; tampering test passes | 1.5 |
| **5. Incident page** | Vue page: bad answer, probe chart, fork side by side, saved test; FastAPI endpoint serving exported JSON | XSS payload tests pass (T7); an incident can be followed without the CLI | 2 |
| **6. Live demo** | Shiori on the server on scripted synthetic conversations; curated incidents; retention; tracefork's OTel export to Project 6 | The 2-minute walkthrough passes; no visitor input path exists | 1.5 |
| **7. Redaction plugin** | Project 15's anonymiser as a tracefork redact plugin (P4) | 0 direct-identifier canaries in exports with redaction on | 1 |
| **8. Third agent (Should)** | A3 (LangGraph) recorded and added to the benchmark as a second scoring round, reported apart | Replay holds; its runs scored | 1 |
| **9. Meaning-level diff (Could)** | Claim-level answer diff (ADR-010); Arthur's labels (P8) | κ reported; shipped only if ≥ 0.6 | 1 |
| **10. Upstream** | Bisect strategy as a PR to tracefork if it passed; bug reports with repros, drafted for Arthur to file (D9) | Drafts ready; nothing sent without Arthur | 0.5 |
| **11. Evidence and write-up** | Results from run records; README numbers and limits; JOURNEY; guide complete; portfolio entry with the portfolio session | Every number traces to a run record; public-repo check passes | 1 |

**Total:** about 17 days with everything, **15 without slices 8 and 9**.

**Order and overlap:** spikes → 0 → 1 → 2 → 3a → 3b → 3c. Slice 3a can
start during 2. Slice 5 can be built during 3c's nights (it reads exported
JSON). Slice 7 is independent once 1 lands.

## The minimum that still impresses

**Spikes + slices 0–3c:** two agents built differently, recorded on
tracefork through Arthur's gateway, a frozen planted-fault set, and one
results page comparing prefix bisection with tracefork's blame and three
judge protocols, with the cost of each. No UI; the README shows the
results table and a probe chart image. That's the claim nobody has
measured; without it the project is a wrapper round tracefork.

## Cut list, in order (first cut first)

1. **Slice 9, meaning-level diff.**
2. **Slice 8, the LangGraph agent.** The framework claim rests on two
   PydanticAI agents written apart; the README says so.
3. **Flight School scenario export (F12)** and the **live check**; the
   CI `verify` and harness export stay.
4. **Slice 7's names and addresses:** secrets and direct identifiers only.
5. **Slice 6, the server demo:** the incident page runs locally, shown by
   a recorded screen capture.
6. **Slice 5, the incident page:** the README and tracefork's report carry
   the story.

Never cut: the frozen set, the judge baselines and E, "replay holds",
secret stripping (T1), the sandbox guard (T3), score-once (T10).

**If spike 1 fails** and the fallback recorder is needed (+3 days), cut
items 1–4 first.

## Cost model

| Item | Cost |
|---|---|
| Models | $0: `qwen3.5:4b`, already on disk (no download) |
| Mac compute | About 13 hours of local inference for the benchmark, over 2–3 nights; spike 3 checks it |
| Disk | Tapes zstd-compressed; raw continuations pruned after scoring; under 1 GB |
| Server | The demo API (under 250 MB RAM) beside Shiori; tapes with retention |
| Dependency | tracefork from PyPI (MIT), plus its small deps (Typer, FastAPI, zstandard, httpx2, anthropic SDK) |
| Hosted model runs | None (D6: no hosted judge) |
| Arthur's time | Reading five docs (~1 h); filing upstream reports; about 1 h of labelling if slice 9 survives |

## Decisions

Arthur accepted every recommendation below on 2026-11-10. The
alternatives are kept so the reasoning stays visible.

| # | Question | Decision |
|---|---|---|
| **D0** | **Is this still the flagship, now that record, replay, fork and per-step blame exist (tracefork, MIT)?** What's left that's new is a measurement (interventional vs judge attribution on live agents, with cost), a cheaper bisect, and the wiring into his stack | **Yes, re-framed:** "how well can you find the step that broke an agent run, and what does it cost?", measured, built on tracefork and his own projects. Rejected: keep it as a smaller project and pick another flagship |
| D1 | Repo name | **`agent-bisect`** (the headline is the method; "flight recorder" is now tracefork's job). Rejected: keep `agent-flight-recorder`. CLI `afr` |
| D2 | Build on tracefork (pinned), and install it from PyPI in spike 1 | Yes; fallback to our own thin recorder only if spike 1 fails |
| D3 | If tracefork can't tape MCP: the Project 4 session adds a tape hook to mcp-gateway | Yes, a small general hook in the gateway, not a second MCP proxy here |
| D4 | Demo agent | Shiori, on scripted synthetic conversations |
| D5 | Visitors: browse curated incidents only, or chat with a recorded Shiori | Browse only (no visitor data recorded) |
| D6 | A capped hosted-model run for a stronger judge | No; publish with the local judge and say so |
| D7 | Licence | MIT, like tracefork and most of his repos |
| D8 | The LangGraph agent (A3) | Only if on schedule (cut item 2) |
| D9 | Contributions to tracefork from his GitHub account: the bisect strategy as a PR if it passes, and bug reports with repros | Yes; drafted here, filed by Arthur |
