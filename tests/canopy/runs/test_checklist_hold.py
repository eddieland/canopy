"""canopy's `pre-push` holds a worker's first push for its repository's checklist (DESIGN §42), against real git.

The push it holds sends nothing, and git's output holds the list; the next goes through, the repository's own `pre-push`
with it. It holds only a push with something to send, in a run with a list, and in the run's last stretch it prints the
list and lets the push through. Its marker is in the slot's own git directory, and counts only for its run.
"""

from __future__ import annotations

import json
import shlex
import time
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

import pytest

from canopy.core import cards, checklist_answers, checklists, commit_hooks, records
from canopy.core.vocab import ItemAnswer
from tests.canopy.helpers import WORKER_DONE, agent_runs, checklists_dir, trailers_on, worker_does, worker_result
from tests.canopy.scenario_helpers import dispatches
from tests.conftest import executable, git

if TYPE_CHECKING:
    from tests.canopy.conftest import Ws
    from tests.canopy.scenario_helpers import Scenario
    from tests.conftest import GitPool

TRAILER: Final = "Co-authored-by: canopy worker <noreply@canopy.invalid>"
BRANCH: Final = "agent/PROJ-1-work"
#: A list of one item, as the operator writes it: about every path, so asked of every push, an empty commit's too.
LIST: Final = "## general-types\n\nA parameter takes the most general type its body needs.\n"
#: A list of an item about every path, and two about paths of their own.
NARROW: Final = (
    "## everywhere\n\nAbout every path.\n\n"
    "## migrations\npaths: services/*/migrations/\n\nA migration has its companion.\n\n"
    "## workflows\npaths: .github/\n\nA workflow's action is pinned.\n"
)
#: `NARROW` with its first item about `src/` alone, so every item names paths.
ALL_NARROW: Final = NARROW.replace("## everywhere\n", "## everywhere\npaths: src/\n")
COMMIT: Final = ["git", "commit", "--quiet", "--allow-empty", "-m", "PROJ-1: the change"]
PUSH: Final = ["git", "push", "--quiet", "origin", f"HEAD:refs/heads/{BRANCH}"]
#: The fix a worker commits once the list is shown.
FIX: Final = [
    "sh",
    "-c",
    "echo 'def f(xs: Iterable[str]): ...' >fix.py && git add fix.py && git commit -q -m 'PROJ-1: fix'",
]
#: A commit of a migration, which the `migrations` item of `NARROW` is about, and `workflows` not.
MIGRATION: Final = [
    "sh",
    "-c",
    (
        "mkdir -p services/billing/migrations && echo 'CREATE TABLE t (a);' >services/billing/migrations/0001.sql "
        "&& git add services && git commit -q -m 'PROJ-1: the migration'"
    ),
]
#: A commit of a workflow, which the `workflows` item of `NARROW` is about.
WORKFLOW: Final = [
    "sh",
    "-c",
    (
        "mkdir -p .github/workflows && echo 'on: push' >.github/workflows/ci.yml "
        "&& git add .github && git commit -q -m 'PROJ-1: the workflow'"
    ),
]
#: The first line of what a held push prints.
HELD: Final = "[canopy] Push held, not rejected: nothing was sent."
#: The first line of what a push that asks no item prints.
UNASKED: Final = "[canopy] Pushed, not held: this push changes none of the paths the items of repo's checklist name"
#: The first line of what a push in the run's last stretch prints.
NEAR: Final = "[canopy] Pushed, not held, as this run is near canopy's deadline."


def ran(agent_log: Path) -> list[dict[str, object]]:
    """Each command the latest worker ran, with its exit code and what it printed."""
    [*_, run] = [r for r in agent_runs(agent_log) if "canopy-worker" in cast("list[str]", r["argv"])]
    return cast("list[dict[str, object]]", run["commands"])


def named_list(agent_log: Path) -> str:
    """Where the latest worker's list is, as the hook names it, so a worker whose output is cut short can read it."""
    [*_, run] = [r for r in agent_runs(agent_log) if "canopy-worker" in cast("list[str]", r["argv"])]
    answers = cast("dict[str, str]", run["env"])[cards.ANSWERS_ENV]
    return f"is below, and in {answers}/{checklists.DIR}/repo{checklists.SUFFIX}, should this output be cut short."


def own_git_dirs(slots: list[Path]) -> list[Path]:
    """Each slot's own git directory, a worktree's in its primary clone's, where the hook keeps its marker."""
    return [Path(git("rev-parse", "--absolute-git-dir", cwd=slot)) for slot in slots]


def test_the_first_push_is_held_with_the_list_and_the_next_goes_through(
    scenario: Scenario,
    worktree_pool: tuple[Path, list[Path]],
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    (checklists_dir(scenario.env) / "repo.md").write_text(LIST)
    primary, slots = worktree_pool
    got = tmp_path / "got"
    # The repository's own pre-push, which every slot shares through its primary clone.
    executable(primary / ".git" / "hooks" / "pre-push", f'#!/bin/sh\necho "$1" >>"{got}"\ncat >>"{got}"\n')
    # One call, as an agent's shell runs it: a commit chained before the push is made, and a push from a script held.
    chained = ["sh", "-c", f"{shlex.join(COMMIT)} && {shlex.join(PUSH)}"]
    run = scenario.run(worker=worker_does(chained, PUSH))
    held, sent = ran(scenario.agent_log)
    assert held["returncode"] != 0
    printed = str(held["stderr"])
    assert printed.startswith(HELD)
    assert named_list(scenario.agent_log) in printed.splitlines()[0]
    assert (
        "`checklist`, under repo, none left out: pass, fixed, held with the reason, or n/a only for an item whose "
        "paths the diff does not touch." in printed
    )
    assert f"\n\n{LIST}" in printed
    assert sent["returncode"] == 0
    assert "[canopy]" not in str(sent["stderr"])
    # The repository's own hook ran once, for the push that went through, with the refs git handed canopy's.
    remote, refs = got.read_text().splitlines()
    assert remote == "origin"
    assert refs.split()[:3] == ["HEAD", git_pool.remote_head(BRANCH), f"refs/heads/{BRANCH}"]
    assert run.status == "done"
    assert trailers_on(git_pool.origin, BRANCH) == [[TRAILER]]
    # The marker is in the slot's own git directory, which a sandboxed run may write and no other slot reads.
    marked = [d / commit_hooks.HOLD_MARKER for d in own_git_dirs(slots) if (d / commit_hooks.HOLD_MARKER).exists()]
    [marker] = marked
    assert marker.parent.parent == primary / ".git" / "worktrees"
    assert marker.read_text().split()[0] == str(run.id)


def test_what_a_run_pushes_after_its_list_is_shown_is_kept_with_its_diff(
    scenario: Scenario,
    worktree_pool: tuple[Path, list[Path]],
    git_pool: GitPool,
) -> None:
    """The commit a push was held at and the one the next push sent: the diff between them is what the list changed."""
    (checklists_dir(scenario.env) / "repo.md").write_text(LIST)
    run = scenario.run(worker=worker_does(COMMIT, PUSH, FIX, PUSH))
    head = git_pool.remote_head(BRANCH)
    assert head is not None
    shown = git("rev-parse", f"{head}^", cwd=git_pool.origin)
    [pushed] = checklist_answers.pushes_of(scenario.conn, run.id)
    assert pushed == records.ChecklistPush(run.id, None, "repo", shown, head)
    diff = checklist_answers.diff_path(run.row.log_path, "repo", shown).read_text()
    assert diff.startswith("diff --git a/fix.py b/fix.py\n")
    assert "+def f(xs: Iterable[str]): ...\n" in diff
    # The notes are taken: the slot outlives the run, and the next run in it starts with none.
    assert not [d for d in own_git_dirs(worktree_pool[1]) if (d / commit_hooks.PUSHES_LOG).exists()]
    shown_run = scenario.operator("show", f"run:{run.id}").out
    assert f"  repo  pushed {shown[:12]}..{head[:12]} after the list, diff " in shown_run


def test_a_run_that_never_pushes_after_its_list_is_kept_to_what_it_left_on_origin(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    """What the worker left, canopy pushes through no hook of the worker's: the stretch ends at the branch on origin."""
    (checklists_dir(scenario.env) / "repo.md").write_text(LIST)
    run = scenario.run(worker=worker_does(COMMIT, PUSH, FIX))
    head = git_pool.remote_head(BRANCH)
    assert head is not None
    [pushed] = checklist_answers.pushes_of(scenario.conn, run.id)
    assert (pushed.shown_sha, pushed.pushed_sha) == (git("rev-parse", f"{head}^", cwd=git_pool.origin), head)
    assert "fix.py" in checklist_answers.diff_path(run.row.log_path, "repo", pushed.shown_sha).read_text()


def test_a_run_never_shown_its_list_keeps_no_push(scenario: Scenario, git_pool: GitPool) -> None:
    (checklists_dir(scenario.env) / "other.md").write_text(LIST)
    run = scenario.run(worker=worker_does(COMMIT, PUSH))
    assert checklist_answers.pushes_of(scenario.conn, run.id) == []


@pytest.mark.parametrize("who", ["another run", "this run, long ago"])
def test_a_marker_of_another_run_or_from_long_ago_counts_for_nothing(
    scenario: Scenario,
    worktree_pool: tuple[Path, list[Path]],
    git_pool: GitPool,
    who: str,
) -> None:
    """A slot outlives its run, so a marker left there by an earlier run, or before a long stretch of work, holds."""
    (checklists_dir(scenario.env) / "repo.md").write_text(LIST)
    now = int(time.time())
    # The journal is new, so the run is the first.
    left = "7 " + str(now) if who == "another run" else f"1 {now - commit_hooks.HOLD_WINDOW_SECONDS - 1}"
    for own in own_git_dirs(worktree_pool[1]):
        (own / commit_hooks.HOLD_MARKER).write_text(f"{left}\n")
    run = scenario.run(worker=worker_does(COMMIT, PUSH, PUSH))
    assert run.id == 1
    _, held, sent = ran(scenario.agent_log)
    assert str(held["stderr"]).startswith(HELD)
    assert sent["returncode"] == 0
    assert git_pool.remote_head(BRANCH) is not None


def test_a_push_with_nothing_to_send_is_not_held(scenario: Scenario, git_pool: GitPool) -> None:
    (checklists_dir(scenario.env) / "repo.md").write_text(LIST)
    # The slot is at main already: git runs pre-push with no ref on its input.
    nothing = ["git", "push", "--quiet", "origin", "HEAD:refs/heads/main"]
    scenario.run(worker=worker_does(nothing, COMMIT, PUSH, PUSH))
    sent_nothing, _, held, sent = ran(scenario.agent_log)
    assert sent_nothing["returncode"] == 0
    assert "[canopy]" not in str(sent_nothing["stderr"])
    # So it marked no hold, and the first push with something to send is held.
    assert str(held["stderr"]).startswith(HELD)
    assert sent["returncode"] == 0


def test_a_run_without_a_list_is_not_held(scenario: Scenario, git_pool: GitPool) -> None:
    (checklists_dir(scenario.env) / "other.md").write_text(LIST)
    run = scenario.run(worker=worker_does(COMMIT, PUSH))
    [_, pushed] = ran(scenario.agent_log)
    assert pushed["returncode"] == 0
    assert "[canopy]" not in str(pushed["stderr"])
    assert run.status == "done"
    [worker] = [r for r in agent_runs(scenario.agent_log) if "canopy-worker" in cast("list[str]", r["argv"])]
    assert commit_hooks.CHECKLISTS_ENV not in cast("dict[str, str]", worker["env"])


def test_with_no_mark_to_add_a_run_with_a_list_is_still_held(scenario: Scenario, git_pool: GitPool) -> None:
    (checklists_dir(scenario.env) / "repo.md").write_text(LIST)
    scenario.configures(trust={"commit_trailer": False})
    run = scenario.run(worker=worker_does(COMMIT, PUSH, PUSH))
    _, held, sent = ran(scenario.agent_log)
    assert str(held["stderr"]).startswith(HELD)
    assert sent["returncode"] == 0
    assert run.status == "done"
    assert trailers_on(git_pool.origin, BRANCH) == [[]]


def test_near_the_deadline_the_list_is_printed_and_the_push_goes_through(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    """In the clock's last stretch a held push risks the run ending unpushed, so it is let through."""
    (checklists_dir(scenario.env) / "repo.md").write_text(LIST)
    timeout = commit_hooks.LAST_STRETCH_SECONDS // 60 - 1
    scenario.configures(runtime={"worker_timeout_minutes": timeout})
    run = scenario.run(worker=worker_does(COMMIT, PUSH))
    [_, pushed] = ran(scenario.agent_log)
    assert pushed["returncode"] == 0
    printed = str(pushed["stderr"])
    assert printed.startswith(NEAR)
    assert named_list(scenario.agent_log) in printed.splitlines()[0]
    assert "if one fails and there is time, commit the fix and push it." in printed
    assert f"\n\n{LIST}" in printed
    assert run.status == "done"
    assert git_pool.remote_head(BRANCH) is not None


def test_near_the_deadline_what_follows_the_first_list_shown_is_kept(scenario: Scenario, git_pool: GitPool) -> None:
    """Every push of the last stretch shows the list and goes through: the stretch runs from the first to the end."""
    (checklists_dir(scenario.env) / "repo.md").write_text(LIST)
    scenario.configures(runtime={"worker_timeout_minutes": commit_hooks.LAST_STRETCH_SECONDS // 60 - 1})
    run = scenario.run(worker=worker_does(COMMIT, PUSH, FIX, PUSH))
    head = git_pool.remote_head(BRANCH)
    assert head is not None
    [pushed] = checklist_answers.pushes_of(scenario.conn, run.id)
    assert (pushed.shown_sha, pushed.pushed_sha) == (git("rev-parse", f"{head}^", cwd=git_pool.origin), head)


#: The run's list, as the hook reads it.
IN_ANSWERS: Final = f'"${cards.ANSWERS_ENV}/{checklists.DIR}/repo{checklists.SUFFIX}"'


@pytest.mark.parametrize(
    "spoils",
    [f"rm {IN_ANSWERS}", f'head -c {checklists.MAX_BYTES + 2} /dev/zero | tr "\\0" x >{IN_ANSWERS}'],
    ids=["missing", "overlong"],
)
def test_a_missing_or_overlong_list_holds_nothing(scenario: Scenario, git_pool: GitPool, spoils: str) -> None:
    """The hook reads what the harness wrote, and holds nothing for a file it did not."""
    (checklists_dir(scenario.env) / "repo.md").write_text(LIST)
    run = scenario.run(worker=worker_does(["sh", "-c", spoils], COMMIT, PUSH))
    [spoiled, _, pushed] = ran(scenario.agent_log)
    assert spoiled["returncode"] == 0
    assert pushed["returncode"] == 0
    assert "[canopy]" not in str(pushed["stderr"])
    assert run.status == "done"


def test_a_joint_runs_slots_are_each_held_with_their_own_list(ws_scenario: Scenario, ws: Ws) -> None:
    yours = checklists_dir(ws_scenario.env)
    (yours / "api.md").write_text("## api-rule\nThe api's rule.\n")
    (yours / "web.md").write_text("## web-rule\nThe web's rule.\n")
    repos = ("api", "web")
    commands = [["git", "-C", name, *command[1:]] for name in repos for command in (COMMIT, PUSH, PUSH)]
    result = json.loads(WORKER_DONE) | {"prs": {name: f"https://example.test/{name}/pr/1" for name in repos}}
    ws_scenario.run(dispatches(repo=repos), worker=worker_does(*commands, result=json.dumps(result)))
    _, api_held, api_sent, _, web_held, web_sent = ran(ws_scenario.agent_log)
    api, web = str(api_held["stderr"]), str(web_held["stderr"])
    assert (api.startswith(HELD), web.startswith(HELD)) == (True, True)
    assert "under api, none" in api
    assert "\n\n## api-rule\nThe api's rule.\n" in api
    assert "web-rule" not in api
    assert "under web, none" in web
    assert "\n\n## web-rule\nThe web's rule.\n" in web
    assert "api-rule" not in web
    assert (api_sent["returncode"], web_sent["returncode"]) == (0, 0)
    api_head, web_head = ws.remote_head("api", BRANCH), ws.remote_head("web", BRANCH)
    assert api_head is not None
    assert web_head is not None
    # Each slot's push after its list is its own, pushed as it was held, with nothing changed between.
    [run_id] = [r[0] for r in ws_scenario.conn.execute("SELECT id FROM runs")]
    pushed = checklist_answers.pushes_of(ws_scenario.conn, run_id)
    assert [(p.repo, p.shown_sha, p.pushed_sha) for p in pushed] == [
        ("api", api_head, api_head),
        ("web", web_head, web_head),
    ]


def test_a_push_is_asked_only_the_items_whose_paths_it_changes(scenario: Scenario, git_pool: GitPool) -> None:
    """The rest are named, left out of what it prints, and recorded unasked: neither the worker's n/a nor unanswered."""
    (checklists_dir(scenario.env) / "repo.md").write_text(NARROW)
    answered = {"repo": {"everywhere": "pass", "migrations": "fixed", "workflows": "n/a"}}
    run = scenario.run(worker=worker_does(MIGRATION, PUSH, PUSH, result=worker_result(checklist=answered)))
    _, held, sent = ran(scenario.agent_log)
    printed = str(held["stderr"])
    assert printed.startswith(HELD)
    assert (
        "This push changes none of the paths of workflows, so only the items below are asked: leave those out of "
        "`checklist` unless a push before asked them, and canopy records them unasked."
    ) in printed
    # The asked items alone, a blank line between them, and git's own line after.
    assert (
        "\n\n## everywhere\n\nAbout every path.\n\n"
        "## migrations\npaths: services/*/migrations/\n\nA migration has its companion.\nerror: "
    ) in printed
    assert "pinned" not in printed
    assert sent["returncode"] == 0
    assert [(a.item, a.answer) for a in checklist_answers.of_run(scenario.conn, run.id)] == [
        ("everywhere", ItemAnswer.PASSED),
        ("migrations", ItemAnswer.FIXED),
        ("workflows", ItemAnswer.UNASKED),
    ]
    found = json.loads(scenario.operator("checklist", "--json").out)
    assert [(i["item"], i["reminded"], i["n/a"], i["unasked"]) for i in found["items"]] == [
        ("everywhere", 1, 0, 0),
        ("migrations", 1, 0, 0),
        ("workflows", 0, 0, 1),
    ]


def test_a_push_that_changes_every_items_paths_is_asked_the_whole_list(scenario: Scenario, git_pool: GitPool) -> None:
    whole = NARROW.replace(".github/", "**/migrations")
    (checklists_dir(scenario.env) / "repo.md").write_text(whole)
    run = scenario.run(worker=worker_does(MIGRATION, PUSH, PUSH))
    printed = str(ran(scenario.agent_log)[1]["stderr"])
    assert printed.startswith(HELD)
    assert "only the items below" not in printed
    assert f"\n\n{whole}" in printed
    # Asked, and answered nothing: unanswered, as before.
    assert {a.answer for a in checklist_answers.of_run(scenario.conn, run.id)} == {ItemAnswer.UNANSWERED}


def test_a_push_that_changes_no_items_paths_goes_through_unheld(scenario: Scenario, git_pool: GitPool) -> None:
    """Only the commits the push sends count: the base's history, which a remote-tracking ref holds, does not."""
    (checklists_dir(scenario.env) / "repo.md").write_text(ALL_NARROW)
    answered = {"repo": {"everywhere": "n/a", "migrations": "pass"}}
    run = scenario.run(worker=worker_does(COMMIT, PUSH, result=worker_result(checklist=answered)))
    [_, pushed] = ran(scenario.agent_log)
    assert pushed["returncode"] == 0
    assert str(pushed["stderr"]).startswith(UNASKED)
    assert git_pool.remote_head(BRANCH) is not None
    # The worker's n/a of an item never asked is the harness's unasked; what it found of one it checked anyway stays.
    assert [(a.item, a.answer) for a in checklist_answers.of_run(scenario.conn, run.id)] == [
        ("everywhere", ItemAnswer.UNASKED),
        ("migrations", ItemAnswer.PASSED),
        ("workflows", ItemAnswer.UNASKED),
    ]
    # Nothing was shown, so no stretch is kept.
    assert checklist_answers.pushes_of(scenario.conn, run.id) == []


def test_an_item_a_later_push_asks_is_asked(scenario: Scenario, git_pool: GitPool) -> None:
    """A push that asks nothing marks no hold, so the next push that changes an item's paths is held and asks it."""
    (checklists_dir(scenario.env) / "repo.md").write_text(ALL_NARROW)
    run = scenario.run(worker=worker_does(COMMIT, PUSH, MIGRATION, PUSH, PUSH))
    _, first, _, held, sent = ran(scenario.agent_log)
    assert str(first["stderr"]).startswith(UNASKED)
    assert str(held["stderr"]).startswith(HELD)
    assert "the paths of everywhere, workflows, so only" in str(held["stderr"])
    assert sent["returncode"] == 0
    assert [(a.item, a.answer) for a in checklist_answers.of_run(scenario.conn, run.id)] == [
        ("everywhere", ItemAnswer.UNASKED),
        ("migrations", ItemAnswer.UNANSWERED),
        ("workflows", ItemAnswer.UNASKED),
    ]


def test_an_item_the_push_after_the_hold_newly_asks_is_shown_and_asked(scenario: Scenario, git_pool: GitPool) -> None:
    """The push after a hold goes through, and reminds of an item whose paths only it changes, which is then asked."""
    (checklists_dir(scenario.env) / "repo.md").write_text(NARROW)
    answered = {"repo": {"everywhere": "pass", "migrations": "pass"}}
    run = scenario.run(worker=worker_does(MIGRATION, PUSH, WORKFLOW, PUSH, result=worker_result(checklist=answered)))
    _, held, _, sent = ran(scenario.agent_log)
    assert str(held["stderr"]).startswith(HELD)
    assert "the paths of workflows, so only" in str(held["stderr"])
    assert sent["returncode"] == 0
    reminded = str(sent["stderr"])
    assert reminded.startswith(
        "[canopy] Pushed, not held: this push changes the paths of workflows, which no push of this run asked before.",
    )
    assert "\n\n## workflows\npaths: .github/\n\nA workflow's action is pinned.\n" in reminded
    # Asked, and left out of the result: unanswered, never unasked.
    assert [(a.item, a.answer) for a in checklist_answers.of_run(scenario.conn, run.id)] == [
        ("everywhere", ItemAnswer.PASSED),
        ("migrations", ItemAnswer.PASSED),
        ("workflows", ItemAnswer.UNANSWERED),
    ]


def test_the_push_after_the_hold_reminds_of_nothing_already_asked(scenario: Scenario, git_pool: GitPool) -> None:
    (checklists_dir(scenario.env) / "repo.md").write_text(NARROW)
    scenario.run(worker=worker_does(MIGRATION, PUSH, FIX, PUSH))
    sent = ran(scenario.agent_log)[-1]
    assert sent["returncode"] == 0
    assert "[canopy]" not in str(sent["stderr"])
