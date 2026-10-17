import pytest
from typer.testing import CliRunner

from ops.cli import app

runner = CliRunner()

COMMANDS = [
    ["data", "import"], ["data", "validate"], ["data", "pick-as-of"],
    ["scenario", "generate"], ["migrate"], ["seed-users"], ["eval"], ["worker"],
    ["recover-job"], ["export-demo"], ["preflight"],
]


@pytest.mark.parametrize("cmd", COMMANDS, ids=" ".join)
def test_help(cmd):
    result = runner.invoke(app, [*cmd, "--help"])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize(
    "cmd",
    [["eval", "--suite", "frozen"],
     ["export-demo"]],
    ids=" ".join,
)
def test_unimplemented_commands_fail_clearly(cmd):
    result = runner.invoke(app, cmd)
    assert result.exit_code == 1
    assert "not implemented until" in result.output


def test_import_missing_directory_fails(tmp_path):
    result = runner.invoke(app, ["data", "import", "--directory", str(tmp_path / "nope")])
    assert result.exit_code == 1
    assert "missing source files" in result.output
