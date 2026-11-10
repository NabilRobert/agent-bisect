"""The sandbox guard (threat T3): a live tool call must not change real data.

A tool server is marked a sandbox in the agent's configuration when it
serves a fake world (Flight School's shop, a Juku test database). Outside a
sandbox only tools the server marks `readOnlyHint` may run live; anything
else is refused before the call leaves the process. Replay never calls a
tool, so it needs no guard.
"""

from mcp import types as mcp_types


class SandboxViolation(RuntimeError):
    """A live call that could change real data was refused."""


def check_live_call(name: str, tool: mcp_types.Tool | None, url: str, is_sandbox: bool) -> None:
    """Raise unless `name` may run live on the server at `url`."""
    if is_sandbox:
        return
    annotations = tool.annotations if tool is not None else None
    if annotations is not None and annotations.read_only_hint is True:
        return
    raise SandboxViolation(
        f"refused live call to {name!r}: {url} is not marked as a sandbox and the tool is not "
        "marked readOnlyHint. Point the agent at a fake world, or mark this server as a sandbox "
        "in its configuration only if it holds no real data."
    )
