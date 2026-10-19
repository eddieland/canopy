"""`canopy chore install` (DESIGN §19): an example chore canopy ships, set up in a workspace, owned by the command."""

import re
import shutil
import tomllib
from pathlib import Path
from unittest import mock

import pytest

from canopy.chores import install
from canopy.cli.main import main
from canopy.core import config, definitions, workspace
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


def test_an_example_that_runs_an_agent_of_canopys_naming_comes_with_it_and_runs_its_copy(canopy_env: CanopyEnv) -> None:
    """Not canopy's own definitions, which change with canopy: the copy stays as installed."""
    canopy_env.write_private(PRIVATE)
    ws = workspace.find(canopy_env.root)
    came_with = 0
    for name in install.available():
        cmd = tomllib.loads((resources.example_chores_dir() / f"{name}.toml").read_text())["chores"][name].get("cmd")
        agent = None if cmd is None else re.search(r"--agent (\S+)", cmd)
        installed = install.install(ws, name)
        if agent is None or not agent[1].startswith("canopy-"):
            assert installed.agent is None, name
            continue
        assert agent[1] not in definitions.agent_names(), name
        agent_dir = canopy_env.state_dir / install.AGENTS_DIR / name
        copied = installed.agent
        assert copied is not None
        assert copied == agent_dir / "agents" / f"{agent[1]}.md"
        assert copied.read_text() == (resources.example_chores_dir() / "agents" / copied.name).read_text()
        assert config.load(canopy_env.root).chores[name].cmd == f"env OPENCODE_CONFIG_DIR={agent_dir} {cmd}"
        came_with += 1
    assert came_with == 3


def test_install_writes_the_prompt_and_the_table_and_keeps_the_rest(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    canopy_env.write_private(PRIVATE)
    assert main(["chore", "install", "memory-tickets"]) == 0
    prompt = canopy_env.state_dir / "chore-prompts" / "memory-tickets.md"
    out = capsys.readouterr().out
    agent = canopy_env.state_dir / "chore-agents" / "memory-tickets" / "agents" / "canopy-memory-tickets.md"
    assert out.startswith(
        f"wrote {prompt}, its agent {agent}, and [chores.memory-tickets] in {canopy_env.private_file}\n"
    )
    assert "keep this chore out of the sandbox" in out
    assert "`canopy chore try memory-tickets`" in out
    text = canopy_env.private_file.read_text()
    assert text.startswith(
        PRIVATE + "\n" + install.MARKER.format(name="memory-tickets") + "\n[chores.memory-tickets]\n"
    )
    assert canopy_env.private_file.stat().st_mode & 0o777 == 0o600
    assert prompt.stat().st_mode & 0o777 == 0o600
    assert agent.stat().st_mode & 0o777 == 0o600
    assert agent.parent.parent.stat().st_mode & 0o777 == 0o700
    chore = config.load(canopy_env.root).chores["memory-tickets"]
    assert chore.prompt == prompt
    assert chore.cwd == canopy_env.root.absolute()
    assert chore.cmd == (
        f"env OPENCODE_CONFIG_DIR={agent.parent.parent} opencode run --agent canopy-memory-tickets --format json "
        "--title={title} {prompt}"
    )


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


def test_the_agents_copy_stays_as_installed_until_the_chore_is_installed_again(
    canopy_env: CanopyEnv, tmp_path: Path
) -> None:
    canopy_env.write_private(PRIVATE)
    ws = workspace.find(canopy_env.root)
    agent = install.install(ws, "memory-tickets").agent
    assert agent is not None
    installed = agent.read_text()
    (agent.parent / "stray.md").write_text("an agent of my own\n")
    upgraded = tmp_path / "upgraded"
    shutil.copytree(resources.example_chores_dir(), upgraded)
    (upgraded / "agents" / agent.name).write_text(installed.replace("changes nothing.", "changes nothing. Upgraded."))
    with mock.patch.object(resources, "example_chores_dir", autospec=True, return_value=upgraded):
        assert agent.read_text() == installed  # an upgraded canopy changes no workspace's copy
        assert install.install(ws, "memory-tickets").replaced
    assert "changes nothing. Upgraded." in agent.read_text()
    assert sorted(p.name for p in agent.parent.iterdir()) == [agent.name]


def test_install_refuses_to_hide_the_user_files_chores(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    canopy_env.write_private(PRIVATE)
    canopy_env.append_user('\n[chores.mine]\nprompt = "~/mine.md"\nevery_minutes = 60\n')
    assert main(["chore", "install", "build-health"]) == 1
    assert f"your chores are in {canopy_env.user_file}" in capsys.readouterr().err
    assert canopy_env.private_file.read_text() == PRIVATE
    assert not (canopy_env.state_dir / "chore-prompts").exists()


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
    assert not (canopy_env.state_dir / "chore-prompts").exists()


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
