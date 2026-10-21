"""Plans archived to a clone of the operator's each live tick (DESIGN §25): exported, committed, pushed, and an item
raised while the archive is not on its upstream."""

from pathlib import Path
from unittest import mock

import pytest

from canopy.core import plans, workspace
from canopy.core.context import DISPATCH_LOCK
from canopy.loop import archive, attention
from tests.canopy.helpers import KEY, PLAN, proposed, waits
from tests.canopy.scenario_helpers import Scenario
from tests.conftest import git


@pytest.fixture
def upstream(tmp_path: Path) -> Path:
    """An empty bare repository, the archive's upstream."""
    path = tmp_path / "plans.git"
    git("init", "--quiet", "--bare", "--initial-branch=main", str(path), cwd=tmp_path)
    return path


@pytest.fixture
def clone(scenario: Scenario, upstream: Path, tmp_path: Path) -> Path:
    """A clone of `upstream`, set as the workspace's plan archive."""
    path = tmp_path / "plans"
    git("clone", "--quiet", str(upstream), str(path), cwd=tmp_path)
    git("config", "user.email", "operator@example.com", cwd=path)
    git("config", "user.name", "Operator", cwd=path)
    scenario.configures(paths={"plan_archive": str(path)})
    return path


def unpushed(scenario: Scenario) -> str | None:
    """The detail of the `archive_unpushed` item on the attention list, if it is there."""
    found = [i.detail for i in attention.current(scenario.conn) if i.reason == archive.REASON]
    return found[0] if found else None


def archived(scenario: Scenario, upstream: Path) -> list[str]:
    """The files the upstream's `main` holds."""
    return git("ls-tree", "-r", "--name-only", "main", cwd=upstream).splitlines()


def test_a_live_tick_pushes_every_plan_and_only_what_changed(scenario: Scenario, clone: Path, upstream: Path) -> None:
    run_id = proposed(scenario.conn, scenario.env.state_dir)
    name = workspace.find(scenario.env.root).name

    scenario.tick(*waits(KEY))

    assert archived(scenario, upstream) == [f"{name}/{KEY}/{run_id}-Proposed.md"]
    assert git("show", f"main:{name}/{KEY}/{run_id}-Proposed.md", cwd=upstream).endswith(PLAN.strip())
    assert unpushed(scenario) is None
    scenario.tick(*waits(KEY))
    assert git("rev-list", "--count", "main", cwd=upstream) == "1", "nothing changed, so nothing is committed"

    plans.approve(
        scenario.conn,
        scenario.env.state_dir,
        KEY,
        channel="cli",
        dispatch_lock=scenario.env.state_dir / DISPATCH_LOCK,
    )
    scenario.tick(*waits(KEY))
    assert git("rev-list", "--count", "main", cwd=upstream) == "2"
    # The plan moved to its approved name: the archive holds it there alone.
    assert archived(scenario, upstream) == [f"{name}/{KEY}/{run_id}-Approved.md"]
    assert 'status: "approved"' in git("show", f"main:{name}/{KEY}/{run_id}-Approved.md", cwd=upstream)


def test_a_commit_names_each_plan_it_archives(scenario: Scenario, clone: Path, upstream: Path) -> None:
    first = proposed(scenario.conn, scenario.env.state_dir)
    second = proposed(scenario.conn, scenario.env.state_dir, key="PROJ-2")
    name = workspace.find(scenario.env.root).name

    scenario.tick(*waits(KEY, "PROJ-2"))
    assert git("log", "-1", "--format=%B", "main", cwd=upstream) == (
        f"Archive 2 plans of {name}: {KEY}, PROJ-2\n\nNew:\n- {KEY}/{first}-Proposed.md\n- PROJ-2/{second}-Proposed.md"
    )

    plans.approve(
        scenario.conn,
        scenario.env.state_dir,
        KEY,
        channel="cli",
        dispatch_lock=scenario.env.state_dir / DISPATCH_LOCK,
    )
    scenario.tick(*waits(KEY, "PROJ-2"))
    assert git("log", "-1", "--format=%B", "main", cwd=upstream) == (
        f"Archive 1 plan of {name}: {KEY}\n\nChanged:\n- {KEY}/{first}-Approved.md (was {first}-Proposed.md)"
    )


def test_a_long_history_goes_in_over_several_ticks(scenario: Scenario, clone: Path, upstream: Path) -> None:
    first = proposed(scenario.conn, scenario.env.state_dir)
    second = proposed(scenario.conn, scenario.env.state_dir, key="PROJ-2")
    name = workspace.find(scenario.env.root).name

    with mock.patch.object(archive, "PER_TICK", 1):
        scenario.tick(*waits(KEY, "PROJ-2"))
        assert archived(scenario, upstream) == [f"{name}/{KEY}/{first}-Proposed.md"]
        assert unpushed(scenario) == "1 plan waits for the next tick's archive: a tick archives at most 1 files"

        scenario.tick(*waits(KEY, "PROJ-2"))

    assert archived(scenario, upstream) == [f"{name}/{KEY}/{first}-Proposed.md", f"{name}/PROJ-2/{second}-Proposed.md"]
    assert unpushed(scenario) is None


def test_a_failed_push_stays_an_item_until_a_tick_pushes(scenario: Scenario, clone: Path, upstream: Path) -> None:
    proposed(scenario.conn, scenario.env.state_dir)
    gone = upstream.with_name("moved.git")
    upstream.rename(gone)

    scenario.tick(*waits(KEY))
    detail = unpushed(scenario)
    assert detail is not None
    assert detail.startswith(f"git push in {clone} failed: ")

    # A dry run pushes nothing and changes nothing in the clone, and the item stays.
    head = git("rev-parse", "HEAD", cwd=clone)
    scenario.tick(*waits(KEY), dry_run=True)
    assert git("rev-parse", "HEAD", cwd=clone) == head
    assert unpushed(scenario) is not None

    gone.rename(upstream)
    scenario.tick(*waits(KEY))
    assert unpushed(scenario) is None
    assert git("rev-parse", "main", cwd=upstream) == head


def test_only_the_archive_is_committed(scenario: Scenario, clone: Path, upstream: Path) -> None:
    (clone / "notes.md").write_text("The operator's own.\n")
    git("add", "notes.md", cwd=clone)
    proposed(scenario.conn, scenario.env.state_dir)

    scenario.tick(*waits(KEY))

    assert "notes.md" not in archived(scenario, upstream)
    assert git("diff", "--cached", "--name-only", cwd=clone) == "notes.md"


def test_a_directory_inside_a_repository_is_never_archived_to(scenario: Scenario, tmp_path: Path) -> None:
    repository = tmp_path / "work"
    git("init", "--quiet", str(repository), cwd=tmp_path)
    inside = repository / "plans"
    inside.mkdir()
    scenario.configures(paths={"plan_archive": str(inside)})
    proposed(scenario.conn, scenario.env.state_dir)

    scenario.tick(*waits(KEY))

    assert unpushed(scenario) == (
        f"{inside} is not a git clone's top level, so no plan is archived there; clone your archive repository there"
    )
    assert list(inside.iterdir()) == []


def test_an_archive_with_no_plan_yet_raises_nothing(scenario: Scenario, clone: Path, upstream: Path) -> None:
    scenario.tick()
    assert unpushed(scenario) is None
    assert git("rev-list", "--all", cwd=upstream) == ""


def test_without_an_archive_nothing_is_raised(scenario: Scenario) -> None:
    proposed(scenario.conn, scenario.env.state_dir)
    scenario.tick(*waits(KEY))
    assert unpushed(scenario) is None
