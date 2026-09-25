from importlib.metadata import version

import pytest

from canopy.cli.main import main
from canopy.infra import resources


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"canopy {version('canopy')}"


@pytest.mark.parametrize("argv", [["--help"], ["-h"], []])
def test_help(capsys: pytest.CaptureFixture[str], argv: list[str]) -> None:
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert out.startswith("Usage: canopy")
    for command in ("init", "skill", "tick", "status", "dispatch", "decide", "attention", "ticket"):
        assert f"  {command} " in out


def test_unknown_argument_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--no-such-flag"]) == 2
    assert "No such option '--no-such-flag'" in capsys.readouterr().err


def test_skill_prints_the_operator_skill(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["skill"]) == 0
    out = capsys.readouterr().out
    assert out == resources.operator_skill().read_text(encoding="utf-8")
    assert out.startswith("---\nname: canopy\n")


def test_skill_help_keeps_the_install_commands_on_their_own_lines(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["skill", "--help"]) == 0
    lines = [line.strip() for line in capsys.readouterr().out.splitlines()]
    assert "mkdir -p ~/.agents/skills/canopy" in lines
    assert "canopy skill > ~/.agents/skills/canopy/SKILL.md" in lines
