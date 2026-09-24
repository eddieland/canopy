from importlib.metadata import version

import pytest

from canopy.cli.main import main


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"canopy {version('canopy')}"


@pytest.mark.parametrize("argv", [["--help"], ["-h"], []])
def test_help(capsys: pytest.CaptureFixture[str], argv: list[str]) -> None:
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert out.startswith("Usage: canopy")
    for command in ("init", "tick", "status", "dispatch", "decide", "attention", "ticket"):
        assert f"  {command} " in out


def test_unknown_argument_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--no-such-flag"]) == 2
    assert "No such option '--no-such-flag'" in capsys.readouterr().err
