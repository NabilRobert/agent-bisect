"""The `afr` command's skeleton."""

from typer.testing import CliRunner

from afr.cli import app


def test_versions_names_agent_bisect_and_the_pinned_tracefork() -> None:
    result = CliRunner().invoke(app, ["versions"])

    assert result.exit_code == 0
    assert "agent-bisect 0.0.0" in result.output
    assert "tracefork 1.0.0" in result.output
