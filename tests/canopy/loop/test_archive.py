"""Plans archived to a clone of the operator's each live tick (DESIGN §25).

They are exported, committed, and pushed, and an item is raised while the archive is not on its upstream.
"""

from pathlib import Path
from unittest import mock

import pytest

from canopy.core import db, plan_threads, plans, workspace
from canopy.core.context import DISPATCH_LOCK
from canopy.loop import archive, attention
from tests.canopy.helpers import KEY, PLAN, PLAN_PROMPT, prompted, proposed, waits
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


def pushed_from_another_clone(upstream: Path, tmp_path: Path, path: str, text: str) -> str:
    """Commit `text` at `path` in a second clone of `upstream` and push it, as another machine would.

    Returns:
        The commit pushed.
    """
    other = tmp_path / "other-clone"
    if not other.exists():
        git("clone", "--quiet", str(upstream), str(other), cwd=tmp_path)
        git("config", "user.email", "operator@example.com", cwd=other)
        git("config", "user.name", "Operator", cwd=other)
    git("pull", "--quiet", cwd=other)
    (other / path).parent.mkdir(parents=True, exist_ok=True)
    (other / path).write_text(text)
    git("add", "--all", cwd=other)
    git("commit", "--quiet", "-m", f"Write {path}", cwd=other)
    git("push", "--quiet", cwd=other)
    return git("rev-parse", "HEAD", cwd=other)


def test_a_live_tick_pushes_every_plan_and_only_what_changed(scenario: Scenario, clone: Path, upstream: Path) -> None:
    run_id = proposed(scenario.conn, scenario.env.state_dir)
    name = workspace.find(scenario.env.root).name

    scenario.tick(*waits(KEY))

    assert archived(scenario, upstream) == [
        f"{name}/{KEY}/{run_id}-PROPOSED.md",
        f"{name}/{KEY}/README.md",
        f"{name}/README.md",
    ]
    assert git("show", f"main:{name}/{KEY}/{run_id}-PROPOSED.md", cwd=upstream).endswith(PLAN.strip())
    assert f"[{run_id}]({run_id}-PROPOSED.md)" in git("show", f"main:{name}/{KEY}/README.md", cwd=upstream)
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
    # The plan moved to its approved name: the archive holds it there alone, and each index links it there.
    assert archived(scenario, upstream) == [
        f"{name}/{KEY}/{run_id}-APPROVED.md",
        f"{name}/{KEY}/README.md",
        f"{name}/README.md",
    ]
    assert f"({KEY}/{run_id}-APPROVED.md)" in git("show", f"main:{name}/README.md", cwd=upstream)
    assert 'status: "approved"' in git("show", f"main:{name}/{KEY}/{run_id}-APPROVED.md", cwd=upstream)


def test_a_commit_names_each_plan_it_archives(scenario: Scenario, clone: Path, upstream: Path) -> None:
    first = proposed(scenario.conn, scenario.env.state_dir)
    second = proposed(scenario.conn, scenario.env.state_dir, key="PROJ-2")
    name = workspace.find(scenario.env.root).name

    scenario.tick(*waits(KEY, "PROJ-2"))
    assert git("log", "-1", "--format=%B", "main", cwd=upstream) == (
        f"Archive 2 plans and 3 READMEs of {name}: {KEY}, PROJ-2\n\n"
        f"New:\n- {KEY}/{first}-PROPOSED.md\n- {KEY}/README.md\n- PROJ-2/{second}-PROPOSED.md\n- PROJ-2/README.md\n"
        "- README.md"
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
        f"Archive 1 plan and 2 READMEs of {name}: {KEY}\n\n"
        f"Changed:\n- {KEY}/{first}-APPROVED.md (was {first}-PROPOSED.md)\n- {KEY}/README.md\n- README.md"
    )


def test_each_plans_prompt_goes_beside_it(scenario: Scenario, clone: Path, upstream: Path) -> None:
    run_id = prompted(scenario.conn, scenario.env.state_dir)
    name = workspace.find(scenario.env.root).name

    scenario.tick(*waits(KEY))

    assert archived(scenario, upstream) == [
        f"{name}/{KEY}/{run_id}-PROMPT.md",
        f"{name}/{KEY}/{run_id}-PROPOSED.md",
        f"{name}/{KEY}/README.md",
        f"{name}/README.md",
    ]
    assert git("show", f"main:{name}/{KEY}/{run_id}-PROMPT.md", cwd=upstream) == PLAN_PROMPT.strip()
    assert git("log", "-1", "--format=%B", "main", cwd=upstream) == (
        f"Archive 1 plan, 1 prompt and 2 READMEs of {name}: {KEY}\n\n"
        f"New:\n- {KEY}/{run_id}-PROMPT.md\n- {KEY}/{run_id}-PROPOSED.md\n- {KEY}/README.md\n- README.md"
    )


def test_an_edited_plans_original_and_the_operators_comments_go_beside_it(
    scenario: Scenario,
    clone: Path,
    upstream: Path,
) -> None:
    run_id = proposed(scenario.conn, scenario.env.state_dir)
    name = workspace.find(scenario.env.root).name
    scenario.tick(*waits(KEY))

    plans.path_for(scenario.env.state_dir, KEY, run_id).write_text(PLAN + "\nThe operator's line.\n")
    plan_threads.add(scenario.conn, KEY, quote="Add the endpoint.", prefix="", suffix="", body="Which one?")
    scenario.tick(*waits(KEY))

    assert archived(scenario, upstream) == [
        f"{name}/{KEY}/{run_id}-ORIGINAL.md",
        f"{name}/{KEY}/{run_id}-PROPOSED.md",
        f"{name}/{KEY}/COMMENTS.md",
        f"{name}/{KEY}/README.md",
        f"{name}/README.md",
    ]
    assert git("show", f"main:{name}/{KEY}/{run_id}-ORIGINAL.md", cwd=upstream) == PLAN.strip()
    assert "\n> Which one?" in git("show", f"main:{name}/{KEY}/COMMENTS.md", cwd=upstream)
    assert git("log", "-1", "--format=%B", "main", cwd=upstream) == (
        f"Archive 1 plan, 1 original, 1 comments file and 1 README of {name}: {KEY}\n\n"
        f"New:\n- {KEY}/{run_id}-ORIGINAL.md\n- {KEY}/COMMENTS.md\n\n"
        f"Changed:\n- {KEY}/{run_id}-PROPOSED.md\n- {KEY}/README.md"
    )


def test_comments_off_archives_none(scenario: Scenario, clone: Path, upstream: Path) -> None:
    scenario.configures(paths={"plan_archive_comments": False})
    proposed(scenario.conn, scenario.env.state_dir)
    plan_threads.add(scenario.conn, KEY, quote="Add the endpoint.", prefix="", suffix="", body="Which one?")
    name = workspace.find(scenario.env.root).name

    scenario.tick(*waits(KEY))

    assert f"{name}/{KEY}/COMMENTS.md" not in archived(scenario, upstream)


def test_a_name_changed_in_case_alone_is_renamed_where_git_ignores_case(
    scenario: Scenario,
    clone: Path,
    upstream: Path,
) -> None:
    run_id = prompted(scenario.conn, scenario.env.state_dir)
    name = workspace.find(scenario.env.root).name
    # As an archive on macOS holds the prompt an earlier canopy wrote in lowercase.
    git("config", "core.ignorecase", "true", cwd=clone)
    (clone / name / KEY).mkdir(parents=True)
    (clone / name / KEY / f"{run_id}-prompt.md").write_text(PLAN_PROMPT)
    git("add", "--all", cwd=clone)
    git("commit", "--quiet", "-m", "Earlier", cwd=clone)

    scenario.tick(*waits(KEY))

    assert git("show", "--name-status", "--format=", "main", cwd=upstream).splitlines() == [
        f"R100\t{name}/{KEY}/{run_id}-prompt.md\t{name}/{KEY}/{run_id}-PROMPT.md",
        f"A\t{name}/{KEY}/{run_id}-PROPOSED.md",
        f"A\t{name}/{KEY}/README.md",
        f"A\t{name}/README.md",
    ]


def test_what_the_operator_staged_in_the_clone_stays_staged(
    scenario: Scenario,
    clone: Path,
    upstream: Path,
) -> None:
    run_id = proposed(scenario.conn, scenario.env.state_dir)
    name = workspace.find(scenario.env.root).name
    (clone / "README.md").write_text("Our plans.\n")
    git("add", "README.md", cwd=clone)

    scenario.tick(*waits(KEY))

    # The clone's own README.md is not the workspace's index.
    assert archived(scenario, upstream) == [
        f"{name}/{KEY}/{run_id}-PROPOSED.md",
        f"{name}/{KEY}/README.md",
        f"{name}/README.md",
    ]
    assert git("diff", "--cached", "--name-only", cwd=clone) == "README.md"


def test_prompts_off_archives_plans_alone(scenario: Scenario, clone: Path, upstream: Path) -> None:
    scenario.configures(paths={"plan_archive_prompts": False})
    run_id = prompted(scenario.conn, scenario.env.state_dir)
    name = workspace.find(scenario.env.root).name

    scenario.tick(*waits(KEY))

    assert archived(scenario, upstream) == [
        f"{name}/{KEY}/{run_id}-PROPOSED.md",
        f"{name}/{KEY}/README.md",
        f"{name}/README.md",
    ]


def test_conversations_go_beside_the_plans_when_asked(scenario: Scenario, clone: Path, upstream: Path) -> None:
    run_id = proposed(scenario.conn, scenario.env.state_dir)
    db.insert_message(
        scenario.conn,
        db.SUBJECT_TICKET,
        KEY,
        source="worker",
        kind="report",
        channel="run",
        run_id=run_id,
        body="Planned it.",
    )
    name = workspace.find(scenario.env.root).name

    scenario.tick(*waits(KEY))
    assert f"{name}/{KEY}/CONVERSATION.md" not in archived(scenario, upstream), "off by default"

    scenario.configures(paths={"plan_archive_conversations": True})
    scenario.tick(*waits(KEY))

    assert archived(scenario, upstream) == [
        f"{name}/{KEY}/{run_id}-PROPOSED.md",
        f"{name}/{KEY}/CONVERSATION.md",
        f"{name}/{KEY}/README.md",
        f"{name}/README.md",
    ]
    assert "\n> Planned it.\n" in git("show", f"main:{name}/{KEY}/CONVERSATION.md", cwd=upstream)
    # Its ticket's index links it now.
    assert git("log", "-1", "--format=%B", "main", cwd=upstream) == (
        f"Archive 1 conversation and 1 README of {name}: {KEY}\n\n"
        f"New:\n- {KEY}/CONVERSATION.md\n\nChanged:\n- {KEY}/README.md"
    )


def test_a_long_history_goes_in_over_several_ticks(scenario: Scenario, clone: Path, upstream: Path) -> None:
    first = proposed(scenario.conn, scenario.env.state_dir)
    second = proposed(scenario.conn, scenario.env.state_dir, key="PROJ-2")
    name = workspace.find(scenario.env.root).name

    with mock.patch.object(archive, "PER_TICK", 2):
        scenario.tick(*waits(KEY, "PROJ-2"))
        assert archived(scenario, upstream) == [f"{name}/{KEY}/{first}-PROPOSED.md", f"{name}/{KEY}/README.md"]
        assert unpushed(scenario) == (
            "3 plans, conversations, comments files, or READMEs wait for the next tick's archive: "
            "a tick archives at most 2 files"
        )

        scenario.tick(*waits(KEY, "PROJ-2"))
        # The index of every ticket waits for the tick that finds every ticket exported.
        assert f"{name}/README.md" not in archived(scenario, upstream)
        assert unpushed(scenario) == (
            "1 plan, conversation, comments file, or README waits for the next tick's archive: "
            "a tick archives at most 2 files"
        )

        scenario.tick(*waits(KEY, "PROJ-2"))

    assert archived(scenario, upstream) == [
        f"{name}/{KEY}/{first}-PROPOSED.md",
        f"{name}/{KEY}/README.md",
        f"{name}/PROJ-2/{second}-PROPOSED.md",
        f"{name}/PROJ-2/README.md",
        f"{name}/README.md",
    ]
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


def test_a_push_the_upstream_refuses_for_its_own_commits_goes_on_top_of_them(
    scenario: Scenario,
    clone: Path,
    upstream: Path,
    tmp_path: Path,
) -> None:
    proposed(scenario.conn, scenario.env.state_dir)
    scenario.tick(*waits(KEY))
    theirs = pushed_from_another_clone(upstream, tmp_path, "other/README.md", "Another workspace's plans.\n")
    second = proposed(scenario.conn, scenario.env.state_dir, key="PROJ-2")
    name = workspace.find(scenario.env.root).name

    scenario.tick(*waits(KEY, "PROJ-2"))

    assert unpushed(scenario) is None
    assert f"{name}/PROJ-2/{second}-PROPOSED.md" in archived(scenario, upstream)
    assert "other/README.md" in archived(scenario, upstream)
    # A fast-forward of what the other clone pushed: its commit is the new one's parent, and nothing is merged.
    assert git("rev-parse", "main^", cwd=upstream) == theirs
    assert git("rev-list", "--merges", "main", cwd=upstream) == ""
    assert git("rev-parse", "HEAD", cwd=clone) == git("rev-parse", "main", cwd=upstream)


def test_a_rebase_that_conflicts_is_aborted_and_stays_an_item(
    scenario: Scenario,
    clone: Path,
    upstream: Path,
    tmp_path: Path,
) -> None:
    proposed(scenario.conn, scenario.env.state_dir)
    scenario.tick(*waits(KEY))
    name = workspace.find(scenario.env.root).name
    # As the same workspace archived from another machine would.
    theirs = pushed_from_another_clone(upstream, tmp_path, f"{name}/README.md", "Another machine's index.\n")
    proposed(scenario.conn, scenario.env.state_dir, key="PROJ-2")
    head = git("rev-parse", "HEAD", cwd=clone)

    scenario.tick(*waits(KEY, "PROJ-2"))

    detail = unpushed(scenario)
    assert detail is not None
    assert detail.startswith(f"its upstream has commits the clone lacks, and git rebase in {clone} failed: ")
    assert git("rev-parse", "main", cwd=upstream) == theirs
    # Aborted: the clone holds its own commit, and no rebase waits there.
    assert git("rev-parse", "HEAD^", cwd=clone) == head
    assert git("status", "--porcelain", cwd=clone) == ""
    assert not any((clone / ".git" / d).exists() for d in ("rebase-merge", "rebase-apply"))


def test_the_operators_changes_in_the_clone_refuse_the_rebase(
    scenario: Scenario,
    clone: Path,
    upstream: Path,
    tmp_path: Path,
) -> None:
    proposed(scenario.conn, scenario.env.state_dir)
    scenario.tick(*waits(KEY))
    theirs = pushed_from_another_clone(upstream, tmp_path, "other/README.md", "Another workspace's plans.\n")
    # Even with the operator's autostash on, their staged file is never set aside.
    git("config", "rebase.autoStash", "true", cwd=clone)
    (clone / "notes.md").write_text("The operator's own.\n")
    git("add", "notes.md", cwd=clone)
    proposed(scenario.conn, scenario.env.state_dir, key="PROJ-2")

    scenario.tick(*waits(KEY, "PROJ-2"))

    detail = unpushed(scenario)
    assert detail is not None
    assert detail.startswith(f"its upstream has commits the clone lacks, and git rebase in {clone} failed: ")
    assert git("rev-parse", "main", cwd=upstream) == theirs
    assert git("diff", "--cached", "--name-only", cwd=clone) == "notes.md"
    assert git("stash", "list", cwd=clone) == ""


def test_only_the_archive_is_committed(scenario: Scenario, clone: Path, upstream: Path) -> None:
    (clone / "notes.md").write_text("The operator's own.\n")
    git("add", "notes.md", cwd=clone)
    proposed(scenario.conn, scenario.env.state_dir)

    scenario.tick(*waits(KEY))

    assert "notes.md" not in archived(scenario, upstream)
    assert git("diff", "--cached", "--name-only", cwd=clone) == "notes.md"


def test_without_the_workspace_dir_plans_go_in_the_top_level(scenario: Scenario, clone: Path, upstream: Path) -> None:
    scenario.configures(paths={"plan_archive_workspace_dir": False})
    (clone / "notes.md").write_text("The operator's own.\n")
    git("add", "notes.md", cwd=clone)
    (clone / "scratch.md").write_text("Not for the remote.\n")
    run_id = proposed(scenario.conn, scenario.env.state_dir)
    name = workspace.find(scenario.env.root).name

    scenario.tick(*waits(KEY))

    assert archived(scenario, upstream) == [f"{KEY}/{run_id}-PROPOSED.md", f"{KEY}/README.md", "README.md"]
    assert git("log", "-1", "--format=%B", "main", cwd=upstream) == (
        f"Archive 1 plan and 2 READMEs of {name}: {KEY}\n\nNew:\n- {KEY}/{run_id}-PROPOSED.md\n- {KEY}/README.md\n"
        "- README.md"
    )
    # What the operator staged stays staged, and what they left untracked stays so.
    assert git("status", "--porcelain", cwd=clone).splitlines() == ["A  notes.md", "?? scratch.md"]
    assert unpushed(scenario) is None


def test_the_operators_own_readme_at_the_top_level_is_never_committed(
    scenario: Scenario,
    clone: Path,
    upstream: Path,
) -> None:
    scenario.configures(paths={"plan_archive_workspace_dir": False})
    (clone / "README.md").write_text("Our plans.\n")
    run_id = proposed(scenario.conn, scenario.env.state_dir)

    scenario.tick(*waits(KEY))

    assert archived(scenario, upstream) == [f"{KEY}/{run_id}-PROPOSED.md", f"{KEY}/README.md"]
    assert (clone / "README.md").read_text() == "Our plans.\n"
    assert git("status", "--porcelain", cwd=clone) == "?? README.md"
    assert unpushed(scenario) is None


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
