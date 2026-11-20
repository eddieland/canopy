"""How an installed example chore and the one canopy ships move apart (DESIGN §19): the list and `canopy chore diff`."""

import contextlib
import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Final
from unittest import mock

import pytest

from canopy.chores import drift, install
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


def test_status_says_when_canopy_ships_a_newer_version_of_an_installed_chore(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    canopy_env.write_private(PRIVATE)
    assert main(["chore", "install", CHORE]) == 0
    capsys.readouterr()
    assert "chore diff" not in status_line(capsys, CHORE)
    with upgraded(tmp_path, agent="changes nothing. Upgraded."):
        assert status_line(capsys, CHORE).endswith(
            f"; canopy ships a newer version, see `canopy chore diff {CHORE}`",
        )
        # Copies it cannot read are as good as unknown: status still prints, and says nothing of them.
        with mock.patch.object(drift, "of", autospec=True, side_effect=PermissionError("denied")):
            assert "chore diff" not in status_line(capsys, CHORE)
    (canopy_env.state_dir / install.ORIGINS_DIR / f"{CHORE}.json").unlink()
    prompt = canopy_env.state_dir / install.PROMPTS_DIR / f"{CHORE}.md"
    prompt.write_text(prompt.read_text().replace("Once a week", "Once a day"))
    assert status_line(capsys, CHORE).endswith(
        f"; differs from the version canopy ships, see `canopy chore diff {CHORE}`",
    )


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


def listed(capsys: pytest.CaptureFixture[str]) -> dict[str, str]:
    """List the examples, and return what the list says of each, by name."""
    assert main(["chore", "install"]) == 0
    lines = capsys.readouterr().out.splitlines()
    return {name: rest.strip() for name, _, rest in (line.partition(" ") for line in lines)}


def status_line(capsys: pytest.CaptureFixture[str], name: str) -> str:
    """Run `canopy status`, and return the line of its chores that names chore `name`."""
    assert main(["status"]) == 0
    [line] = [line for line in capsys.readouterr().out.splitlines() if line.startswith(f"  {name}  ")]
    return line


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
