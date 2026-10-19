"""`canopy chore install` (DESIGN §19): an example chore canopy ships, set up in a workspace, owned by the command."""

import tomllib

import pytest

from canopy.chores import install
from canopy.cli.main import main
from canopy.core import config, workspace
from canopy.infra import resources
from tests.canopy.helpers import in_run
from tests.conftest import CanopyEnv

PRIVATE = """\
# My labels.
[tracker]
labels = ["agent-ready-tester"]
"""


def test_every_example_has_a_prompt_and_a_table_that_installs(canopy_env: CanopyEnv) -> None:
    examples = install.available()
    shipped = {path.stem for path in resources.example_chores_dir().glob("*.md")} - {"README"}
    assert set(examples) == shipped
    canopy_env.write_private(PRIVATE)
    for name in examples:
        installed = install.install(workspace.find(canopy_env.root), name)
        assert installed.next_steps, f"{name}.toml says nothing about what to do before it runs"
        assert all(len(line) <= 120 for line in installed.next_steps)
    chores = config.load(canopy_env.root).chores
    assert sorted(chores) == examples
    for name, chore in chores.items():
        assert chore.prompt.read_text() == (resources.example_chores_dir() / f"{name}.md").read_text()
        assert chore.cwd in {None, canopy_env.root.absolute()}


def test_install_writes_the_prompt_and_the_table_and_keeps_the_rest(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    canopy_env.write_private(PRIVATE)
    assert main(["chore", "install", "memory-tickets"]) == 0
    prompt = canopy_env.home / ".config" / "canopy" / "chores" / "memory-tickets.md"
    out = capsys.readouterr().out
    assert out.startswith(f"wrote {prompt}, and [chores.memory-tickets] in {canopy_env.private_file}\n")
    assert "define the canopy-memory-tickets agent" in out
    assert "`canopy chore try memory-tickets`" in out
    text = canopy_env.private_file.read_text()
    assert text.startswith(
        PRIVATE + "\n" + install.MARKER.format(name="memory-tickets") + "\n[chores.memory-tickets]\n"
    )
    assert canopy_env.private_file.stat().st_mode & 0o777 == 0o600
    chore = config.load(canopy_env.root).chores["memory-tickets"]
    assert chore.prompt == prompt
    assert chore.cwd == canopy_env.root.absolute()
    assert chore.cmd == "opencode run --agent canopy-memory-tickets --format json --title={title} {prompt}"


def test_installing_again_replaces_the_prompt_and_the_whole_table(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    after = '\n# My own chore.\n[chores.mine]\nprompt = "~/mine.md"\nevery_minutes = 60\n'
    canopy_env.write_private(PRIVATE)
    assert main(["chore", "install", "build-health"]) == 0
    installed = canopy_env.private_file.read_text()
    prompt = config.load(canopy_env.root).chores["build-health"].prompt
    prompt.write_text("my edited prompt\n")
    edited = installed.replace("every_minutes = 120", "every_minutes = 30\nmax_findings = 9")
    canopy_env.write_private(edited + after)
    capsys.readouterr()
    assert main(["chore", "install", "build-health"]) == 0
    assert capsys.readouterr().out.startswith("replaced ")
    assert canopy_env.private_file.read_text() == installed + after
    assert prompt.read_text() == (resources.example_chores_dir() / "build-health.md").read_text()
    assert set(config.load(canopy_env.root).chores) == {"build-health", "mine"}


def test_install_refuses_to_hide_the_user_files_chores(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    canopy_env.write_private(PRIVATE)
    canopy_env.append_user('\n[chores.mine]\nprompt = "~/mine.md"\nevery_minutes = 60\n')
    assert main(["chore", "install", "build-health"]) == 1
    assert f"your chores are in {canopy_env.user_file}" in capsys.readouterr().err
    assert canopy_env.private_file.read_text() == PRIVATE
    assert not (canopy_env.home / ".config" / "canopy" / "chores").exists()


@pytest.mark.parametrize(
    "form",
    [
        '[chores]\nbuild-health.prompt = "~/mine.md"\nbuild-health.every_minutes = 60\n',
        '[chores]\nbuild-health = { prompt = "~/mine.md", every_minutes = 60 }\n',
    ],
)
def test_install_refuses_a_table_it_cannot_replace_and_writes_nothing(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str], form: str
) -> None:
    canopy_env.write_private(PRIVATE + form)
    assert main(["chore", "install", "build-health"]) == 1
    assert "cannot replace [chores.build-health]" in capsys.readouterr().err
    assert canopy_env.private_file.read_text() == PRIVATE + form
    assert not (canopy_env.home / ".config" / "canopy" / "chores").exists()


def test_install_lists_the_examples_and_refuses_an_unknown_one_a_missing_file_and_inside_runs(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["chore", "install"]) == 0
    assert capsys.readouterr().out.split() == install.available()
    assert main(["chore", "install", "nope"]) == 1
    assert "no example chore named 'nope'; there are: build-health, " in capsys.readouterr().err
    assert main(["chore", "install", "build-health"]) == 1
    assert f"there is no private config at {canopy_env.private_file}" in capsys.readouterr().err
    canopy_env.write_private(PRIVATE)
    with in_run("chore-3"):
        assert main(["chore", "install", "build-health"]) == 1
        assert "chore install refused (inside_run)" in capsys.readouterr().err
    assert "chores" not in tomllib.loads(canopy_env.private_file.read_text())
