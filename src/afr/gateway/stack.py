"""A1's tools behind mcp-gateway, for a whole session of runs.

Flight School's tool server gives each conversation its own URL token, but
a gateway's upstream URL is fixed in its config. So one conversation is
registered for the session with a `SwitchableTools`, and each run switches
it to that run's fresh shop. The gateway runs as a subprocess with a config
written here: one route, one caller key made for the session, the rules
detector (the model layer when its folder is given), and `log` on a
suspicious output, so the run goes on as it would without a gateway and the
verdict is only recorded.
"""

# Flight School ships typed code without a `py.typed` marker; pyright still reads its sources.
# pyright: reportMissingTypeStubs=false

import hashlib
import os
import secrets
import shlex
import socket
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx2
import yaml
from flight_school.conversation.agent import AgentTools
from flight_school.http.tool_server import running_tool_server
from flight_school.log import ToolCall
from flight_school.world.schema import World
from flight_school.world.shop import SHOP_TOOLS, FakeShop

GATEWAY_COMMAND_ENV = "AFR_GATEWAY_COMMAND"
CALLER = "afr"
ROUTE = "shop"
STARTUP_SECONDS = 30.0
STOP_SECONDS = 10.0
# What the model layer needs besides its folder (mcp-gateway's README defaults).
MODEL_THRESHOLD = 0.999


class SwitchableTools(AgentTools):
    """The tool server calls `call`; this sends each call to the current run's shop."""

    def __init__(self, world: World) -> None:
        super().__init__(FakeShop(world))
        self.current = AgentTools(FakeShop(world))

    def call(self, tool: str, arguments: dict[str, object]) -> ToolCall:
        return self.current.call(tool, arguments)


@dataclass(frozen=True)
class GatewayStack:
    url: str  # the gateway's route for the shop
    key: str  # the session's caller key, sent as a bearer token
    audit_log: Path
    tools: SwitchableTools


def gateway_command() -> list[str]:
    command = os.environ.get(GATEWAY_COMMAND_ENV)
    if not command:
        raise RuntimeError(
            f"{GATEWAY_COMMAND_ENV} is not set: name the command that runs mcp-gateway, e.g. "
            "'uv run --project <a checkout of mcp-gateway at main> mcp-gateway'"
        )
    return shlex.split(command)


def gateway_config(upstream: str, key: str, audit_log: Path, model_dir: Path | None) -> str:
    detector: dict[str, object] = {"rules": True}
    if model_dir is not None:
        detector["model"] = {"dir": str(model_dir), "threshold": MODEL_THRESHOLD}
    config: dict[str, object] = {
        "upstreams": {ROUTE: {"transport": "http", "url": upstream}},
        "callers": {
            CALLER: {"key_sha256": hashlib.sha256(key.encode()).hexdigest(), "policy": "bench"}
        },
        "policies": {
            "bench": {
                "on_suspicious": "log",
                "routes": {ROUTE: {"tools": {name: {} for name in sorted(SHOP_TOOLS)}}},
            }
        },
        "detector": detector,
        "audit": {"path": str(audit_log), "fsync": False},
    }
    return yaml.safe_dump(config, sort_keys=False)


@contextmanager
def running_gateway_stack(world: World, model_dir: Path | None = None) -> Iterator[GatewayStack]:
    """Flight School's tool server and a gateway in front of it, until the block ends."""
    tools = SwitchableTools(world)
    key = secrets.token_urlsafe(32)
    with running_tool_server() as server, tempfile.TemporaryDirectory() as work:
        audit_log = Path(work) / "audit.jsonl"
        config_path = Path(work) / "gateway.yaml"
        config_path.write_text(gateway_config(server.register(tools), key, audit_log, model_dir))
        port = free_port()
        command = [*gateway_command(), "serve", "--config", str(config_path), "--port", str(port)]
        with running_process(command, Path(work) / "gateway.log") as process:
            base = f"http://127.0.0.1:{port}"
            wait_until_healthy(base, process, Path(work) / "gateway.log")
            yield GatewayStack(
                url=f"{base}/mcp/{ROUTE}/", key=key, audit_log=audit_log, tools=tools
            )


@contextmanager
def running_process(command: list[str], log_path: Path) -> Iterator[subprocess.Popen[bytes]]:
    with log_path.open("wb") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)  # noqa: S603
        try:
            yield process
        finally:
            process.terminate()
            process.wait(timeout=STOP_SECONDS)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def wait_until_healthy(base: str, process: subprocess.Popen[bytes], log_path: Path) -> None:
    deadline = time.monotonic() + STARTUP_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            tail = log_path.read_text(errors="replace")[-2000:]
            raise RuntimeError(
                f"mcp-gateway exited with code {process.returncode} on start:\n{tail}"
            )
        try:
            if httpx2.get(f"{base}/healthz", timeout=1.0).status_code == 200:
                return
        except httpx2.TransportError:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"mcp-gateway did not answer {base}/healthz within {STARTUP_SECONDS:.0f} s")
