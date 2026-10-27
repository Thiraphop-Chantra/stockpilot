"""Command-line interface contract."""

from stockpilot.cli import main


def test_version_prints_package_version(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "stockpilot 0.1.0"


def test_unknown_command_is_a_usage_error(capsys):
    assert main(["no-such-command"]) == 2
    assert "invalid choice" in capsys.readouterr().err
