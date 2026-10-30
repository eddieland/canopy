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
from typing import TYPE_CHECKING, cast

import pytest

from canopy.core import cards, checklists, commit_hooks
from tests.canopy.helpers import WORKER_DONE, agent_runs, checklists_dir, trailers_on, worker_does
from tests.canopy.scenario_helpers import dispatches
from tests.conftest import executable, git

if TYPE_CHECKING:
    from tests.canopy.conftest import Ws
    from tests.canopy.scenario_helpers import Scenario
    from tests.conftest import GitPool

TRAILER = "Co-authored-by: canopy worker <noreply@canopy.invalid>"
BRANCH = "agent/PROJ-1-work"
#: A list of one item, as the operator writes it.
LIST = "## general-types\npaths: src/\n\nA parameter takes the most general type its body needs.\n"
COMMIT = ["git", "commit", "--quiet", "--allow-empty", "-m", "PROJ-1: the change"]
PUSH = ["git", "push", "--quiet", "origin", f"HEAD:refs/heads/{BRANCH}"]
#: The first line of what a held push prints.
HELD = "[canopy] Push held, not rejected: nothing was sent."
#: The first line of what a push in the run's last stretch prints.
NEAR = "[canopy] Pushed, not held, as this run is near canopy's deadline."


def ran(agent_log: Path) -> list[dict[str, object]]:
    """Each command the latest worker ran, with its exit code and what it printed."""
    [*_, run] = [r for r in agent_runs(agent_log) if "canopy-worker" in cast("list[str]", r["argv"])]
    return cast("list[dict[str, object]]", run["commands"])


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
    assert "`checklist`, under repo: pass, fixed, held with the reason, or n/a." in printed
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
    assert "if one fails and there is time, commit the fix and push it." in printed
    assert f"\n\n{LIST}" in printed
    assert run.status == "done"
    assert git_pool.remote_head(BRANCH) is not None


#: The run's list, as the hook reads it.
IN_ANSWERS = f'"${cards.ANSWERS_ENV}/{checklists.DIR}/repo{checklists.SUFFIX}"'


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
    del result["pr"]
    ws_scenario.run(dispatches(repo=repos), worker=worker_does(*commands, result=json.dumps(result)))
    _, api_held, api_sent, _, web_held, web_sent = ran(ws_scenario.agent_log)
    api, web = str(api_held["stderr"]), str(web_held["stderr"])
    assert (api.startswith(HELD), web.startswith(HELD)) == (True, True)
    assert "under api:" in api
    assert "\n\n## api-rule\nThe api's rule.\n" in api
    assert "web-rule" not in api
    assert "under web:" in web
    assert "\n\n## web-rule\nThe web's rule.\n" in web
    assert "api-rule" not in web
    assert (api_sent["returncode"], web_sent["returncode"]) == (0, 0)
    assert ws.remote_head("api", BRANCH) is not None
    assert ws.remote_head("web", BRANCH) is not None
