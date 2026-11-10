# Guide

A plain-English walk through agent-bisect, kept in step with the code.
Each slice adds to it. Today only the scaffold exists.

## The flow

So far there is one command:

1. `afr versions` (`src/afr/cli.py: show_versions`) prints this package's
   version and tracefork's. Both will go into every run record, so a
   number in the results can be traced to the code that made it.

The full flow (record a run, plant a fault, bisect it, save the incident)
is added slice by slice.

## Glossary

| Word | Meaning | Where |
|---|---|---|
| **tracefork** | The library this repo builds on: it records an agent's model calls to a tape, replays them exactly, and forks a run at a step | dependency, pinned in `pyproject.toml` |
| **Tape** | tracefork's recording of one run: each request and response, byte for byte | tracefork |
| **Public-repo check** | A script that fails the build if a tracked file holds a server address, a private note, a recording or a denylisted name | `scripts/check_public.py` |

## Where to change things

- **Add a command:** a function with `@app.command` in `src/afr/cli.py`
  that calls into the package; test the package function, not the CLI.
- **Add a word the public repo must never contain:** append its SHA-256
  (`printf %s word | shasum -a 256`) to `scripts/public_denylist.sha256`.
- **Upgrade tracefork:** change the pin in `pyproject.toml`, run
  `uv lock`, and re-run the replay-holds check (threat T11).
