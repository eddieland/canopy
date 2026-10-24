import contextlib
import importlib
import os
import pkgutil
import sys
from importlib.metadata import version
from pathlib import Path
from unittest import mock

import click
import pytest

from canopy import cli as cli_package
from canopy.cli import launcher
from canopy.cli import main as cli_main
from canopy.cli.main import main
from canopy.infra import procs, resources
from tests.canopy.helpers import present
from tests.conftest import CanopyEnv


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"canopy {version('canopy')}"


def test_the_console_script_answers_version_without_loading_the_cli() -> None:
    # A version check should cost little: click, the config, and pydantic are most of a start-up.
    code = (
        "import sys; sys.argv = ['canopy', '--version']; from canopy.cli import launcher; "
        "code = launcher.main(); print(code, *sys.modules, sep='\\n')"
    )
    result = procs.SubprocessRunner().run([sys.executable, "-c", code])
    assert result.ok, result.stderr
    said, code, *imported = result.stdout.splitlines()
    assert (said, code) == (f"canopy {version('canopy')}", "0")
    assert {"click", "pydantic", "canopy.cli.main", "canopy.core.config"}.isdisjoint(imported)


def test_python_m_canopy_answers_version_as_the_console_script_does() -> None:
    result = procs.SubprocessRunner().run([sys.executable, "-m", "canopy", "--version"])
    assert result.ok, result.stderr
    assert result.stdout == f"canopy {version('canopy')}\n"


@pytest.mark.parametrize("argv", [["--help"], ["--version", "--help"], ["--help", "--version"]])
def test_the_console_script_hands_anything_but_version_alone_to_the_cli(
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
) -> None:
    with mock.patch.object(sys, "argv", ["canopy", *argv]):
        assert launcher.main() == 0
    out = capsys.readouterr().out
    # click handles the flag it reads first.
    assert out.startswith("Usage: canopy") if argv[0] == "--help" else out == f"canopy {version('canopy')}\n"


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


@pytest.mark.parametrize(("argv", "loads"), [(["--version"], set[str]()), (["decide", "--help"], {"journal"})])
def test_a_command_imports_only_its_own_module(argv: list[str], loads: set[str]) -> None:
    # The overseer calls `canopy decide` and its kin many times a tick; each start-up pays for every module it imports.
    code = f"import sys; from canopy.cli.main import main; main({argv!r}); print(*sys.modules, sep='\\n')"
    result = procs.SubprocessRunner().run([sys.executable, "-c", code])
    assert result.ok, result.stderr
    imported = set(result.stdout.splitlines())
    assert {f"canopy.cli.{module}" for module, _ in cli_main.COMMANDS.values()} & imported == {
        f"canopy.cli.{module}" for module in loads
    }


def test_every_command_in_a_command_module_is_registered_under_its_own_name() -> None:
    # Every click command a command module defines, by where it is defined; the root group is not one of them.
    defined: dict[tuple[str, str], click.Command] = {}
    for info in pkgutil.iter_modules(cli_package.__path__):
        module = importlib.import_module(f"canopy.cli.{info.name}")
        defined.update(
            ((info.name, attr), v)
            for attr, v in vars(module).items()
            if isinstance(v, click.Command) and v is not cli_main.cli
        )
    subcommands = {id(sub) for c in defined.values() if isinstance(c, click.Group) for sub in c.commands.values()}
    top_level = {where for where, c in defined.items() if id(c) not in subcommands}
    assert set(cli_main.COMMANDS.values()) == top_level
    for name in cli_main.COMMANDS:
        command = present(cli_main.cli.get_command(click.Context(cli_main.cli), name))
        assert command.name == name


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
    assert "canopy skill --install" in lines
    assert "canopy skill --install ~/.claude/skills" in lines


def test_skill_install_saves_it_in_the_home_skills_directory(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    saved = tmp_path / ".agents" / "skills" / "canopy" / "SKILL.md"
    with mock.patch.dict(os.environ, {"HOME": str(tmp_path)}):
        assert main(["skill", "--install"]) == 0
    assert saved.read_text(encoding="utf-8") == resources.operator_skill().read_text(encoding="utf-8")
    assert capsys.readouterr().out == f"wrote {saved}\n"


def test_skill_install_saves_it_in_the_directory_given_over_an_older_one(tmp_path: Path) -> None:
    saved = tmp_path / "skills" / "canopy" / "SKILL.md"
    saved.parent.mkdir(parents=True)
    saved.write_text("an older canopy's skill\n", encoding="utf-8")
    assert main(["skill", "--install", str(tmp_path / "skills")]) == 0
    assert saved.read_text(encoding="utf-8") == resources.operator_skill().read_text(encoding="utf-8")


def test_skill_install_reports_a_directory_it_cannot_write(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    (tmp_path / "file").touch()
    assert main(["skill", "--install", str(tmp_path / "file")]) == 1
    assert "could not save the skill" in capsys.readouterr().err


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
    assert complete(capsys, "canopy chore ") == ["plain,history", "plain,install", "plain,try"]
    assert complete(capsys, "canopy chore install memory-") == ["plain,memory-tickets"]
    assert complete(capsys, "canopy review ") == [
        "plain,discard",
        "plain,draft",
        "plain,edit",
        "plain,eval",
        "plain,noise",
        "plain,publish",
        "plain,show",
    ]
    assert complete(capsys, "canopy ticket ") == []


def test_help_still_lists_the_overseers_commands(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--help"]) == 0
    listed = {line.split()[0] for line in capsys.readouterr().out.splitlines() if line.startswith("  ")}
    assert {"attention", "decide", "dispatch", "mirror", "queried", "ticket"} <= listed


def test_completion_completes_repository_names_from_the_workspace(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    canopy_env.write_shared(
        canopy_env.shared_file.read_text().replace(
            "[tracker]",
            '[repos.web]\nurl = "https://example.test/acme/web.git"\n\n[tracker]',
        ),
    )
    assert complete(capsys, "canopy grant PROJ-1 implement --repo ") == ["plain,repo", "plain,web"]
    assert complete(capsys, "canopy grant PROJ-1 implement --repo w") == ["plain,web"]


def test_completion_completes_chore_names_from_the_config(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    chores = "".join(
        f"\n[chores.{name}]\nprompt = '~/chores/{name}.md'\ncmd = 'agent run {{prompt}}'\nevery_minutes = 60\n"
        for name in ("queue-age", "build-health")
    )
    canopy_env.append_user(chores)
    assert complete(capsys, "canopy chore run ") == ["plain,build-health", "plain,queue-age"]
    assert complete(capsys, "canopy chore try q") == ["plain,queue-age"]


def test_completion_offers_no_names_where_the_config_does_not_load(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
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
