"""mcp-gateway on the tape (slice 2, ADR-005): tool calls through Arthur's
gateway, and the gateway's verdict on each tool step.

- `stack.py` runs A1's tools behind a gateway process for a session;
- `verdicts.py` reads the gateway's audit log and matches each audited call
  to a taped tool step.

mcp-gateway is a private repo, so it isn't a dependency: the command that
starts it is named by `AFR_GATEWAY_COMMAND`, and CI tests only the log
reading.
"""
