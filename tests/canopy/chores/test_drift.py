"""How an installed example chore and the one canopy ships move apart (DESIGN §19): the list and `canopy chore diff`."""

import contextlib
import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Final
from unittest import mock

import pytest

from canopy.chores import install
from canopy.cli.main import main
from canopy.core import config, db
from canopy.infra import resources
from tests.canopy.helpers import in_run
from tests.conftest import CanopyEnv

PRIVATE: Final = '[tracker]\nlabels = ["agent-ready-tester"]\n'
#: The chore the tests install: it comes with an agent.
CHORE: Final = "memory-tickets"
#: Its agent's file name.
AGENT: Final = "canopy-memory-tickets.md"


def test_install_keeps_what_it_installed_from_beside_the_copies(canopy_env: CanopyEnv) -> None:
    canopy_env.write_private(PRIVATE)
    assert main(["chore", "install", CHORE]) == 0
    origin = canopy_env.state_dir / install.ORIGINS_DIR / f"{CHORE}.json"
    assert origin.stat().st_mode & 0o777 == 0o600
    assert origin.parent.stat().st_mode & 0o777 == 0o700
    assert json.loads(origin.read_text()) == {
        "version": db.CANOPY_VERSION,
        "prompt": (resources.example_chores_dir() / f"{CHORE}.md").read_text(),
        "agent_file": AGENT,
        "agent": (resources.example_chores_dir() / "agents" / AGENT).read_text(),
    }
    assert main(["chore", "install", "build-health"]) == 0
    assert json.loads((origin.parent / "build-health.json").read_text())["agent"] is None


def test_the_list_marks_installed_chores_and_says_when_canopy_ships_a_newer_one(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    canopy_env.write_private(PRIVATE)
    assert main(["chore", "install", CHORE]) == 0
    capsys.readouterr()
    assert listed(capsys) == {CHORE: "installed"} | {name: "" for name in install.available() if name != CHORE}
    prompt = canopy_env.state_dir / install.PROMPTS_DIR / f"{CHORE}.md"
    prompt.write_text(prompt.read_text() + "My own line.\n")
    agent = canopy_env.state_dir / install.AGENTS_DIR / CHORE / "agents" / AGENT
    agent.write_text(agent.read_text().replace("# canopy: model\n", '# canopy: model\nmodel: "acme/fake-model-1"\n'))
    assert listed(capsys)[CHORE] == "installed"  # the operator's edits, and the model canopy writes, are not canopy's
    with upgraded(tmp_path, agent="changes nothing. Upgraded."):
        assert listed(capsys)[CHORE] == f"installed; canopy ships a newer version, see `canopy chore diff {CHORE}`"
        assert main(["chore", "install", CHORE]) == 0
        capsys.readouterr()
        assert listed(capsys)[CHORE] == "installed"


def test_diff_shows_what_canopy_changed_and_what_the_operator_changed(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    canopy_env.write_private(PRIVATE)
    assert main(["chore", "install", CHORE]) == 0
    capsys.readouterr()
    assert main(["chore", "diff", CHORE]) == 0
    out = capsys.readouterr().out
    assert out == (
        f"What canopy changed since chore {CHORE} was installed: canopy {db.CANOPY_VERSION}'s against canopy "
        f"{db.CANOPY_VERSION}'s.\n(no change)\n\nWhat you changed: canopy {db.CANOPY_VERSION}'s against your copy.\n"
        "(no change)\n"
    )
    prompt = canopy_env.state_dir / install.PROMPTS_DIR / f"{CHORE}.md"
    prompt.write_text(prompt.read_text() + "My own line.\n")
    agent = canopy_env.state_dir / install.AGENTS_DIR / CHORE / "agents" / AGENT
    agent.write_text(agent.read_text().replace("# canopy: model\n", '# canopy: model\nmodel: "acme/fake-model-1"\n'))
    with upgraded(tmp_path, agent="changes nothing. Upgraded."):
        assert main(["chore", "diff", CHORE]) == 0
    canopys, yours = capsys.readouterr().out.split("\nWhat you changed: ")
    assert f"--- installed-from/{AGENT}\n+++ shipped/{AGENT}\n" in canopys
    assert "\n+description: canopy chore that reads agent memory for what should become a ticket. " in canopys
    assert "changes nothing. Upgraded.\n" in canopys
    assert "My own line." not in canopys
    assert f"--- installed-from/{CHORE}.md\n+++ yours/{CHORE}.md\n" in yours
    assert "\n+My own line.\n" in yours
    assert "Upgraded." not in yours
    assert "fake-model" not in canopys + yours


def test_a_chore_installed_before_the_record_is_compared_with_what_canopy_ships_now(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    canopy_env.write_private(PRIVATE)
    assert main(["chore", "install", CHORE]) == 0
    (canopy_env.state_dir / install.ORIGINS_DIR / f"{CHORE}.json").unlink()
    capsys.readouterr()
    assert listed(capsys)[CHORE] == "installed"
    prompt = canopy_env.state_dir / install.PROMPTS_DIR / f"{CHORE}.md"
    prompt.write_text(prompt.read_text().replace("Once a week", "Once a day"))
    assert listed(capsys)[CHORE] == f"installed; differs from the version canopy ships, see `canopy chore diff {CHORE}`"
    assert main(["chore", "diff", CHORE]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"chore {CHORE} was installed before canopy kept what it installed it from, so this is only ")
    assert f"--- yours/{CHORE}.md\n+++ shipped/{CHORE}.md\n" in out
    assert "\n-Once a day" in out
    assert "\n+Once a week" in out
    assert AGENT not in out
    # A record that does not parse is none.
    (canopy_env.state_dir / install.ORIGINS_DIR / f"{CHORE}.json").write_text("{")
    assert main(["chore", "diff", CHORE]) == 0
    assert "was installed before canopy kept" in capsys.readouterr().out


def test_diff_refuses_a_chore_not_installed_and_inside_runs(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    canopy_env.write_private(PRIVATE)
    assert main(["chore", "diff", "build-health"]) == 1
    assert "chore build-health is not installed here; `canopy chore install` lists the examples" in (
        capsys.readouterr().err
    )
    assert main(["chore", "install", "build-health"]) == 0
    with in_run("chore-3"):
        assert main(["chore", "diff", "build-health"]) == 1
        assert "chore diff refused (inside_run)" in capsys.readouterr().err


def test_an_agent_canopy_renames_with_its_text_unchanged_is_a_newer_version(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    canopy_env.write_private(PRIVATE)
    assert main(["chore", "install", CHORE]) == 0
    capsys.readouterr()
    with upgraded(tmp_path, agent="changes nothing.", renamed="canopy-memory-to-tickets"):
        assert listed(capsys)[CHORE] == f"installed; canopy ships a newer version, see `canopy chore diff {CHORE}`"
        assert main(["chore", "diff", CHORE]) == 0
    canopys, yours = capsys.readouterr().out.split("\nWhat you changed: ")
    assert f"renamed: installed-from/{AGENT} -> shipped/canopy-memory-to-tickets.md, the text unchanged\n" in canopys
    assert yours.endswith("(no change)\n")


def test_the_list_in_a_workspace_whose_map_does_not_load_says_why(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (canopy_env.root / config.WORKSPACE_FILE_NAME).write_text("[repos.api\n")
    assert main(["chore", "install"]) == 1
    assert "chore install: " in capsys.readouterr().err


def test_the_list_outside_a_workspace_names_the_examples(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with contextlib.chdir(tmp_path):
        assert main(["chore", "install"]) == 0
    assert capsys.readouterr().out.split() == install.available()


def test_merge_carries_canopys_change_into_the_copies_and_keeps_the_operators_edits(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    canopy_env.write_private(PRIVATE)
    assert main(["chore", "install", CHORE]) == 0
    assert main(["chore", "install", CHORE, "--merge"]) == 0
    assert capsys.readouterr().out.endswith(
        f"chore {CHORE}: canopy ships what it was installed from; nothing to merge\n",
    )
    prompt = canopy_env.state_dir / install.PROMPTS_DIR / f"{CHORE}.md"
    prompt.write_text(prompt.read_text() + "My own line.\n")
    agent = canopy_env.state_dir / install.AGENTS_DIR / CHORE / "agents" / AGENT
    agent.write_text(agent.read_text().replace("# canopy: model\n", '# canopy: model\nmodel: "acme/fake-model-1"\n'))
    agent.write_text(agent.read_text() + "My own rule.\n")
    private = config.private_config_path(canopy_env.root)
    private.write_text(private.read_text().replace("[chores.", "# My own note.\n[chores.", 1))
    table = private.read_text()
    with upgraded(tmp_path, agent="changes nothing. Upgraded."):
        assert main(["chore", "install", CHORE, "--merge"]) == 0
        assert capsys.readouterr().out == (
            f"merged canopy's change into {agent}\n"
            f"[chores.{CHORE}] is left as it was; `canopy chore diff {CHORE}` shows what you changed\n"
        )
        assert "changes nothing. Upgraded.\n" in agent.read_text()
        assert agent.read_text().endswith("My own rule.\n")
        assert "fake-model" not in agent.read_text()  # canopy writes it again at the chore's next run
        assert agent.stat().st_mode & 0o777 == 0o600
        assert prompt.read_text().endswith("My own line.\n")  # canopy changed nothing there, so it was not written
        assert private.read_text() == table
        # The record now names what canopy ships, so the list calls it current, with the operator's edits still theirs.
        assert listed(capsys)[CHORE] == "installed"
        assert main(["chore", "diff", CHORE]) == 0
        canopys, yours = capsys.readouterr().out.split("\nWhat you changed: ")
        assert canopys.endswith("(no change)\n")
        assert "\n+My own line.\n" in yours
        assert "\n+My own rule.\n" in yours
        assert main(["chore", "install", CHORE, "--merge"]) == 0
        assert "nothing to merge" in capsys.readouterr().out


def test_merge_on_a_conflict_writes_nothing_and_says_where(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    canopy_env.write_private(PRIVATE)
    assert main(["chore", "install", CHORE]) == 0
    agent = canopy_env.state_dir / install.AGENTS_DIR / CHORE / "agents" / AGENT
    agent.write_text(agent.read_text().replace("changes nothing.", "changes nothing, as I say."))
    mine = agent.read_text()
    origin = (canopy_env.state_dir / install.ORIGINS_DIR / f"{CHORE}.json").read_text()
    capsys.readouterr()
    prompt = canopy_env.state_dir / install.PROMPTS_DIR / f"{CHORE}.md"
    their_prompt = prompt.read_text()
    with upgraded(tmp_path, agent="changes nothing. Upgraded."):
        # A change to the prompt that would merge cleanly is not written either.
        shipped_prompt = resources.example_chores_dir() / f"{CHORE}.md"
        shipped_prompt.write_text(shipped_prompt.read_text() + "Canopy's new line.\n")
        assert main(["chore", "install", CHORE, "--merge"]) == 1
        assert capsys.readouterr().err == (
            f"chore install --merge: canopy's change conflicts with yours in {AGENT} (1), so nothing was written; "
            f"`canopy chore diff {CHORE}` shows both sides\n"
        )
        assert listed(capsys)[CHORE] == f"installed; canopy ships a newer version, see `canopy chore diff {CHORE}`"
    assert agent.read_text() == mine
    assert prompt.read_text() == their_prompt
    assert (canopy_env.state_dir / install.ORIGINS_DIR / f"{CHORE}.json").read_text() == origin


def test_merge_takes_canopys_whole_where_the_operator_changed_nothing(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    canopy_env.write_private(PRIVATE)
    assert main(["chore", "install", CHORE]) == 0
    agent = canopy_env.state_dir / install.AGENTS_DIR / CHORE / "agents" / AGENT
    with upgraded(tmp_path, agent="changes nothing. Upgraded."):
        shipped = (resources.example_chores_dir() / "agents" / AGENT).read_text()
        assert main(["chore", "install", CHORE, "--merge"]) == 0
    assert agent.read_text() == shipped
    assert f"merged canopy's change into {agent}\n" in capsys.readouterr().out


def test_merge_keeps_a_file_the_operator_put_beside_the_agent(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    canopy_env.write_private(PRIVATE)
    assert main(["chore", "install", CHORE]) == 0
    agents = canopy_env.state_dir / install.AGENTS_DIR / CHORE / "agents"
    beside = agents / "a-notes.md"  # sorts before the agent
    beside.write_text("My notes.\n")
    with upgraded(tmp_path, agent="changes nothing. Upgraded."):
        assert main(["chore", "install", CHORE, "--merge"]) == 0
    assert f"merged canopy's change into {agents / AGENT}\n" in capsys.readouterr().out
    assert beside.read_text() == "My notes.\n"
    assert "changes nothing. Upgraded.\n" in (agents / AGENT).read_text()


def test_merge_of_copies_that_already_hold_canopys_change_says_so(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    canopy_env.write_private(PRIVATE)
    assert main(["chore", "install", CHORE]) == 0
    agent = canopy_env.state_dir / install.AGENTS_DIR / CHORE / "agents" / AGENT
    capsys.readouterr()
    with upgraded(tmp_path, agent="changes nothing. Upgraded."):
        agent.write_text((resources.example_chores_dir() / "agents" / AGENT).read_text())
        assert main(["chore", "install", CHORE, "--merge"]) == 0
        assert capsys.readouterr().out == f"chore {CHORE}: your copies already hold canopy's change; nothing to merge\n"
        assert listed(capsys)[CHORE] == "installed"


def test_merge_refuses_what_it_cannot_carry(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    canopy_env.write_private(PRIVATE)
    assert main(["chore", "install", "--merge"]) == 2
    assert "--merge needs the NAME of an installed chore" in capsys.readouterr().err
    assert main(["chore", "install", CHORE, "--merge"]) == 1
    assert f"chore {CHORE} is not installed here; `canopy chore install {CHORE}` installs it" in capsys.readouterr().err
    assert main(["chore", "install", CHORE]) == 0
    with upgraded(tmp_path, agent="changes nothing.", renamed="canopy-memory-to-tickets"):
        assert main(["chore", "install", CHORE, "--merge"]) == 1
    assert f"canopy changed which agent the chore runs ({AGENT}), which a merge does not carry" in (
        capsys.readouterr().err
    )
    agent = canopy_env.state_dir / install.AGENTS_DIR / CHORE / "agents" / AGENT
    agent.unlink()
    with upgraded(tmp_path / "again", agent="changes nothing. Upgraded."):
        assert main(["chore", "install", CHORE, "--merge"]) == 1
    assert f"your copy of {AGENT} is gone; installing again puts canopy's back" in capsys.readouterr().err
    with upgraded(tmp_path / "prompt", agent="changes nothing."):
        # canopy changed only the prompt, and the agent's copy is still gone.
        shipped_prompt = resources.example_chores_dir() / f"{CHORE}.md"
        shipped_prompt.write_text(shipped_prompt.read_text() + "Canopy's new line.\n")
        assert main(["chore", "install", CHORE, "--merge"]) == 1
    assert f"your copy of {AGENT} is gone" in capsys.readouterr().err
    assert main(["chore", "install", CHORE]) == 0
    prompt = canopy_env.state_dir / install.PROMPTS_DIR / f"{CHORE}.md"
    prompt.write_bytes(prompt.read_bytes() + b"My own line \xff.\n")
    with upgraded(tmp_path / "bytes", agent="changes nothing."):
        shipped_prompt = resources.example_chores_dir() / f"{CHORE}.md"
        shipped_prompt.write_text("Canopy's first line.\n" + shipped_prompt.read_text())
        assert main(["chore", "install", CHORE, "--merge"]) == 1
    assert f"your copy of {CHORE}.md is not UTF-8, so a merge would change bytes you wrote" in capsys.readouterr().err
    assert prompt.read_bytes().endswith(b"My own line \xff.\n")
    (canopy_env.state_dir / install.ORIGINS_DIR / f"{CHORE}.json").unlink()
    assert main(["chore", "install", CHORE, "--merge"]) == 1
    assert "was installed before canopy kept what it installed it from, so there is nothing to merge from" in (
        capsys.readouterr().err
    )
    with in_run("chore-3"):
        assert main(["chore", "install", CHORE, "--merge"]) == 1
        assert "chore install refused (inside_run)" in capsys.readouterr().err


def listed(capsys: pytest.CaptureFixture[str]) -> dict[str, str]:
    """List the examples, and return what the list says of each, by name."""
    assert main(["chore", "install"]) == 0
    lines = capsys.readouterr().out.splitlines()
    return {name: rest.strip() for name, _, rest in (line.partition(" ") for line in lines)}


@contextlib.contextmanager
def upgraded(tmp_path: Path, *, agent: str, renamed: str | None = None) -> Iterator[None]:
    """Ship, while the block runs, the examples with the memory chore's agent's `changes nothing.` made `agent`.

    With `renamed`, the agent is shipped under that name, its file and the table's command both.
    """
    shipped = tmp_path / "upgraded"
    shutil.copytree(resources.example_chores_dir(), shipped)
    definition = shipped / "agents" / AGENT
    definition.write_text(definition.read_text().replace("changes nothing.", agent))
    if renamed is not None:
        definition.rename(definition.with_name(f"{renamed}.md"))
        table = shipped / f"{CHORE}.toml"
        table.write_text(table.read_text().replace(f"--agent {AGENT.removesuffix('.md')} ", f"--agent {renamed} "))
    with mock.patch.object(resources, "example_chores_dir", autospec=True, return_value=shipped):
        yield
