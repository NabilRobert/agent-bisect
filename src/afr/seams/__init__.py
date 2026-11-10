"""Where a run touches the outside world, and where tracefork tapes it.

Two seams, both tracefork's own pieces under a thin wrapper:
- `model.py`: model calls, at tracefork's HTTP transport (ADR-004);
- `tools.py`: MCP tool calls, at tracefork's JSON-RPC tool seam (ADR-005).
Both note each step in a shared `StepLog`, because tracefork keeps model and
tool exchanges in two separate lists and bisection needs one order.
"""
