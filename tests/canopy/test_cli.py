import contextlib
import os
import sys
from importlib.metadata import version
from pathlib import Path
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.infra import procs, resources
from tests.conftest import CanopyEnv


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


@pytest.mark.parametrize("group", ["chore", "review", "ticket", "workspace", "notify", "sandbox"])
def test_a_group_without_a_command_prints_its_help(capsys: pytest.CaptureFixture[str], group: str) -> None:
    assert main([group]) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith(f"Usage: canopy {group} ")
    assert "Commands:" in captured.out
    assert captured.err == ""


def test_the_cli_starts_without_the_web_server() -> None:
    # The overseer and workers run `canopy` many times a tick; fastapi and uvicorn would double each start-up.
    code = "import sys, canopy.cli.main; print(sorted({'fastapi', 'uvicorn'} & set(sys.modules)))"
    result = procs.SubprocessRunner().run([sys.executable, "-c", code])
    assert result.ok, result.stderr
    assert result.stdout.strip() == "[]"


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


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_completion_prints_the_shells_script(capsys: pytest.CaptureFixture[str], shell: str) -> None:
    assert main(["completion", shell]) == 0
    out = capsys.readouterr().out
    assert "_CANOPY_COMPLETE" in out
    assert f"{shell}_complete" in out


def test_completion_refuses_a_shell_it_has_no_script_for(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["completion", "tcsh"]) == 2
    assert "'tcsh' is not one of" in capsys.readouterr().err


def test_completion_help_keeps_the_load_commands_on_their_own_lines(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["completion", "--help"]) == 0
    lines = [line.strip() for line in capsys.readouterr().out.splitlines()]
    assert """echo 'eval "$(canopy completion bash)"' >> ~/.bashrc""" in lines
    assert "canopy completion fish > ~/.config/fish/completions/canopy.fish" in lines


def test_completion_completes_commands(capsys: pytest.CaptureFixture[str]) -> None:
    assert complete(capsys, "canopy work") == ["plain,workspace"]


def test_completion_leaves_out_the_overseers_commands(capsys: pytest.CaptureFixture[str]) -> None:
    commands = complete(capsys, "canopy ")
    assert "plain,status" in commands
    for overseers in ("attention", "decide", "dispatch", "mirror", "queried", "ticket", "_run", "_chore", "_review"):
        assert f"plain,{overseers}" not in commands
    assert complete(capsys, "canopy chore ") == ["plain,try"]
    assert complete(capsys, "canopy review ") == ["plain,show"]
    assert complete(capsys, "canopy ticket ") == []


def test_help_still_lists_the_overseers_commands(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--help"]) == 0
    listed = {line.split()[0] for line in capsys.readouterr().out.splitlines() if line.startswith("  ")}
    assert {"attention", "decide", "dispatch", "mirror", "queried", "ticket"} <= listed


def test_completion_completes_repository_names_from_the_workspace(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    canopy_env.write_shared(
        canopy_env.shared_file.read_text().replace(
            "[tracker]", '[repos.web]\nurl = "https://example.test/acme/web.git"\n\n[tracker]'
        )
    )
    assert complete(capsys, "canopy grant PROJ-1 implement --repo ") == ["plain,repo", "plain,web"]
    assert complete(capsys, "canopy grant PROJ-1 implement --repo w") == ["plain,web"]


def test_completion_completes_chore_names_from_the_config(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    chores = "".join(
        f"\n[chores.{name}]\nprompt = '~/chores/{name}.md'\ncmd = 'agent run {{prompt}}'\nevery_minutes = 60\n"
        for name in ("queue-age", "build-health")
    )
    canopy_env.write_user(canopy_env.user_file.read_text() + chores)
    assert complete(capsys, "canopy chore run ") == ["plain,build-health", "plain,queue-age"]
    assert complete(capsys, "canopy chore try q") == ["plain,queue-age"]


def test_completion_offers_no_names_where_the_config_does_not_load(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    canopy_env.write_shared("not toml [")
    assert complete(capsys, "canopy grant PROJ-1 implement --repo ") == []
    assert complete(capsys, "canopy chore run ") == []
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    with contextlib.chdir(outside):
        assert complete(capsys, "canopy grant PROJ-1 implement --repo ") == []
        assert complete(capsys, "canopy chore run ") == []


def complete(capsys: pytest.CaptureFixture[str], words: str) -> list[str]:
    """What the bash script hears from canopy when the operator presses Tab after `words`."""
    cword = len(words.split()) - (0 if words.endswith(" ") else 1)
    variables = {"_CANOPY_COMPLETE": "bash_complete", "COMP_WORDS": words, "COMP_CWORD": str(cword)}
    with mock.patch.dict(os.environ, variables), pytest.raises(SystemExit) as exit_info:
        main([])
    assert exit_info.value.code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    return captured.out.split()
