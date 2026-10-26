"""Units and joint runs (DESIGN §18, ROADMAP M7): a ticket's work per repository, desks, and all-or-nothing leases."""

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import db, pr_list
from canopy.core.vocab import Phase, ResumeReason, RunKind
from canopy.infra import lock, procs
from canopy.loop import attention
from canopy.runs import desks
from canopy.runs.dispatch import DISPATCH_LOCK
from tests.canopy.conftest import Ws, seed_pools
from tests.canopy.helpers import (
    BRANCH,
    LABEL,
    InlineRunner,
    agent_runs,
    decisions,
    in_tick,
    last_tick,
    pool_statuses,
    present,
    waits,
    worker_does,
)
from tests.canopy.scenario_helpers import Scenario, dispatches, pushes, sets_phase
from tests.conftest import executable, git

#: The branch PROJ-1's first implement names, with its slug.
LOGIN = "agent/PROJ-1-login"
PRS = {"api": "https://x.test/api/pull/1", "web": "https://x.test/web/pull/2", "docs": "https://x.test/docs/pull/3"}
# Each PR's own title as the worker reports it: web's spans lines, and docs is not one of the run's repositories.
TITLES = {"api": "PROJ-1: add the endpoint", "web": "PROJ-1: call\n  the endpoint", "docs": "PROJ-1: document it"}


def dispatch(key: str, *args: str, kind: str = "implement") -> list[str]:
    return ["dispatch", key, "--label", LABEL, "--kind", kind, *args]


def push_in(repo: str, message: str = "PROJ-1: the change") -> list[list[str]]:
    """Commands a worker in a desk runs to commit and push in one repository, through its link."""
    return [
        ["git", "-C", repo, "commit", "--quiet", "--allow-empty", "-m", message],
        ["git", "-C", repo, "push", "--quiet", "origin", f"HEAD:refs/heads/{BRANCH}"],
    ]


def done(prs: dict[str, str], titles: dict[str, str] | None = None) -> str:
    result = {"status": "done", "branch": BRANCH, "prs": prs, "summary": "changed both"}
    return json.dumps(result if titles is None else {**result, "pr_titles": titles})


def slots_of(conn: sqlite3.Connection, run_id: int) -> dict[str, Path]:
    return {str(s.repo): Path(s.slot_path) for s in db.run_slots(conn, run_id)}


def test_a_joint_implement_works_in_a_desk_and_opens_a_pr_per_repository(
    ws_scenario: Scenario,
    ws: Ws,
    treehouse_state: Path,
) -> None:
    """M7 acceptance, against the fakes: one run over two repositories pushes both and records both PRs."""
    conn = ws_scenario.conn
    worker = worker_does(["readlink", "api"], *push_in("api"), *push_in("web"), result=done(PRS, TITLES))
    run = ws_scenario.run(dispatches(repo=("api", "web", "api")), worker=worker)
    assert run.status == "done", run.printed.out

    # One run, one slot in each repository's pool, and the worker in a desk linking them.
    slots = slots_of(conn, run.id)
    assert list(slots) == ["api", "web"]
    desk = ws.root / "desks" / "PROJ-1"
    [w] = agent_runs(ws_scenario.agent_log)
    assert w["cwd"] == str(desk)
    assert [c["returncode"] for c in w["commands"]] == [0, 0, 0, 0, 0]
    assert w["commands"][0]["stdout"].strip() == os.path.relpath(slots["api"], desk)
    assert not desk.exists()  # removed when the run ended
    assert pool_statuses(treehouse_state) == ["available", "available"]

    for name in ("api", "web"):
        assert ws.remote_head(name, BRANCH) == git("rev-parse", "HEAD", cwd=slots[name])
    # Each unit has the ticket's branch and its own PR; a PR for a repository the run was not in is not recorded.
    units = {u.repo: u for u in db.units(conn, "PROJ-1")}
    assert {r: (u.branch, u.pr_url) for r, u in units.items()} == {
        "api": (BRANCH, PRS["api"]),
        "web": (BRANCH, PRS["web"]),
    }
    assert json.loads(run.row["result_json"])["prs"] == {"api": PRS["api"], "web": PRS["web"]}
    # Each PR's own title is recorded by its URL, on one line; docs's is not.
    titles = {"api": TITLES["api"], "web": "PROJ-1: call the endpoint"}
    assert json.loads(run.row["result_json"])["pr_titles"] == titles
    assert {r["url"]: r["pr_title"] for r in pr_list.pull_requests(conn, 10)} == {PRS[r]: t for r, t in titles.items()}
    [(action, rationale)] = decisions(conn, int(run.row["tick_id"]))
    assert action == "dispatch:implement"
    assert rationale == f"run 1: {BRANCH} in api at {slots['api']}, web at {slots['web']}; desk {desk}; label {LABEL}"

    prompt = run.prompt
    assert f"ticket PROJ-1 in {desk}." in prompt
    assert "This is a joint run over 2 repositories" in prompt
    assert f"- `api` at `{desk / 'api'}`: branch `{BRANCH}` from `main`; PR: not recorded;" in prompt
    assert f"- `web` at `{desk / 'web'}`: branch `{BRANCH}` from `main`; PR: not recorded;" in prompt
    assert "Each PR's body links its sibling PRs and says which one merges first." in prompt
    assert '"prs":{"api":"<url or null>","web":"<url or null>"}' in prompt
    assert '"pr_titles":{"api":"<its title or null>","web":"<its title or null>"}' in prompt

    # The next run is told each unit's PR.
    resume = dispatches(kind=RunKind.RESUME, repo=("web", "api"), reasons=[ResumeReason.REVIEW])
    review_fix = ws_scenario.run(resume, worker=pushes(repos=("web", "api")))
    assert f"- `web` at `{desk / 'web'}`: branch `{BRANCH}` from `main`; PR: {PRS['web']}." in review_fix.prompt


def test_leases_are_all_or_nothing(ws_scenario: Scenario, ws: Ws, treehouse_state: Path) -> None:
    state = json.loads(treehouse_state.read_text())
    state["pools"][str(ws.clone("web"))].update(max_trees=1, slots=[{"name": "1", "path": "/busy", "status": "in-use"}])
    treehouse_state.write_text(json.dumps(state))

    # Refused as the tick starts it, after the overseer (DESIGN §40), the dispatch starts no run.
    refused = ws_scenario.refuses(dispatches(repo=("api", "web")))
    assert [a for a, _ in refused] == ["refused:no_slot"]
    assert refused[0][1].startswith("web: treehouse get exited 1: ")
    # api's slot was leased first, and returned before the refusal was recorded.
    assert pool_statuses(treehouse_state) == ["available", "in-use"]
    calls: list[list[str]] = json.loads(treehouse_state.read_text())["calls"]
    assert [c[0] for c in calls] == ["get", "get", "return"]


def test_a_joint_run_over_sandboxed_and_unsandboxed_repositories_is_refused(
    ws_scenario: Scenario,
    treehouse_state: Path,
) -> None:
    ws_scenario.configures(runtime={"sandbox_repos": ["api"]})

    # One run is one command, so it cannot run in a sandbox for api and outside one for web (DESIGN §24).
    [(action, reason)] = ws_scenario.refuses(dispatches(repo=("api", "web")))
    assert action == "refused:mixed_sandbox"
    assert reason.startswith("api runs sandboxed and web does not (runtime.sandbox_repos)")
    assert pool_statuses(treehouse_state) == ["available", "available"]  # refused before any lease
    # web alone is not sandboxed, and runs as before.
    assert ws_scenario.run(dispatches(repo="web"), worker=pushes(repos=("web",))).status == "done"


def test_a_joint_run_is_unpushed_if_any_repository_is(ws_scenario: Scenario, ws: Ws, treehouse_state: Path) -> None:
    hook = ws.origins["web"] / "hooks" / "pre-receive"
    executable(hook, "#!/bin/sh\necho 'push refused by test hook' >&2\nexit 1\n")
    worker = worker_does(*push_in("api"), *push_in("web"), result=done({"api": PRS["api"]}))
    run = ws_scenario.run(dispatches(repo=("api", "web")), worker=worker)

    assert run.status == "unpushed"
    note = json.loads(run.row["result_json"])["harness"]
    assert note.startswith(f"web: commits on {BRANCH} are not on origin; the push failed: ")
    assert "api" not in note.split(":", 1)[1]  # api's branch is pushed, so only web is named
    assert ws.remote_head("api", BRANCH) is not None
    assert pool_statuses(treehouse_state) == ["available", "available"]
    [item] = attention.from_runs(ws_scenario.conn)
    assert (item.ticket_key, item.reason) == ("PROJ-1", "unpushed")


def test_units_have_their_own_attempts_and_share_the_branch(ws_scenario: Scenario) -> None:
    conn = ws_scenario.conn
    login = pushes(LOGIN)

    def ci_fix(repo: str) -> list[str]:
        return dispatches(kind=RunKind.RESUME, repo=repo, reasons=[ResumeReason.CI])

    assert ws_scenario.run(dispatches(repo="api", slug="login"), worker=login).kind == RunKind.IMPLEMENT
    # The first implement named the branch; a later one adds a unit on the same branch, and may not rename it.
    assert ws_scenario.refuses(dispatches(repo="web", slug="other")) == [
        (
            "refused:bad_slug",
            "PROJ-1's branch is agent/PROJ-1-login, named by its first implement; leave out slug (--slug)",
        ),
    ]
    ws_scenario.run(dispatches(repo="web", slug="login"), worker=login)
    ws_scenario.run(ci_fix("api"), worker=login)
    ws_scenario.run(dispatches(repo="api"), worker=login)  # api's second implement: its limit is 2
    limit = "PROJ-1 in api has had 2 implement runs and the limit is 2"
    assert ws_scenario.refuses(dispatches(repo=("api", "web"))) == [
        ("refused:attempt_limit", limit),
        ("attention:attempt_limit", limit),
    ]
    [item] = [d for d in db.decisions_for_tick(conn, last_tick(conn).id) if d.action == "attention:attempt_limit"]
    assert item.repo == "api"  # the item is about the unit at its limit
    ws_scenario.run(dispatches(repo="web"), worker=login)  # web has had one
    assert {str(r["branch"]) for r in conn.execute("SELECT branch FROM runs")} == {LOGIN}
    assert [str(r["action"]) for r in conn.execute("SELECT action FROM decisions ORDER BY id")] == [
        "dispatch:implement",
        "refused:bad_slug",
        "dispatch:implement",
        "dispatch:resume",
        "dispatch:implement",
        "refused:attempt_limit",
        "attention:attempt_limit",
        "dispatch:implement",
    ]

    # The CI cooldown is per unit too: api's resume for CI just ended, web has had none.
    [(action, _)] = ws_scenario.refuses(ci_fix("api"))
    assert action == "refused:cooldown"
    ws_scenario.run(ci_fix("web"), worker=login)


def test_a_dispatch_reads_the_ticket_branch_under_the_dispatch_lock(ws: Ws, treehouse_state: Path) -> None:
    """A first implement that waited for the lock sees the branch another one named meanwhile, and may not rename it."""
    seed_pools(ws, treehouse_state)
    conn = ws.journal()
    with in_tick(conn) as tick_id:
        codes: list[int] = []

        def second() -> None:
            codes.append(main(dispatch("PROJ-1", "--repo", "web", "--slug", "other"), runner=InlineRunner()))

        with lock.hold(ws.state_dir / DISPATCH_LOCK, wait=True):
            waiting = threading.Thread(target=second)
            waiting.start()
            time.sleep(0.5)  # long enough for it to reach the lock
            # Another dispatch's first implement names the branch while this one waits.
            db.touch_ticket(conn, "PROJ-1", str(ws.root))
            conn.execute("UPDATE tickets SET branch = ? WHERE key = ?", ("agent/PROJ-1-login", "PROJ-1"))
        waiting.join(timeout=30)
        assert codes == [1]
        assert decisions(conn, tick_id) == [
            (
                "refused:bad_slug",
                "PROJ-1's branch is agent/PROJ-1-login, named by its first implement; leave out slug (--slug)",
            ),
        ]


def test_the_state_block_shows_each_unit(ws_scenario: Scenario) -> None:
    ws_scenario.run(
        dispatches(repo=("api", "web")),
        worker=worker_does(*push_in("api"), *push_in("web"), result=done(PRS)),
    )
    # The overseer records web's phase and cursor, and the ticket's own; the next tick's state block shows them.
    ws_scenario.tick(
        sets_phase("PROJ-1", Phase.CI_RED, repo="web", cursor="ci=9"),
        sets_phase("PROJ-1", Phase.RUNNING, cursor="comment=c-1"),
        *waits("PROJ-1"),
    )
    ws_scenario.tick(*waits("PROJ-1"), dry_run=True)

    [ticket] = ws_scenario.state()["tickets"]
    assert (ticket["phase"], ticket["branch"], ticket["cursors"]) == (
        "running",
        BRANCH,
        {"comment": "c-1", "message": None},
    )
    no_limit = {"implement": 1, "resume": 0}
    assert ticket["units"] == [
        {
            "repo": "api",
            "branch": BRANCH,
            "pr_url": PRS["api"],
            "phase": None,
            "cursors": {"review": None, "ci": None},
            "attempts": no_limit,
            "ci_cooldown_until": None,
        },
        {
            "repo": "web",
            "branch": BRANCH,
            "pr_url": PRS["web"],
            "phase": "ci_red",
            "cursors": {"review": None, "ci": 9},
            "attempts": no_limit,
            "ci_cooldown_until": None,
        },
    ]
    assert ticket["last_run"]["repos"] == [{"repo": "api", "base": "main"}, {"repo": "web", "base": "main"}]


def test_journal_commands_name_a_unit(ws_scenario: Scenario) -> None:
    conn = ws_scenario.conn
    with ws_scenario.ticking():
        # A review or ci cursor is a unit's: of a ticket with no unit, in a workspace of several, it needs --repo.
        reviewed = "4127"
        refused = ws_scenario.overseer("ticket", "set", "PROJ-1", "--cursor", f"review={reviewed}", code=1)
        assert refused.err == (
            "Error: repo is required (--repo): a review cursor belongs to one unit, and PROJ-1 has no unit yet: name "
            "one of api, web\n"
        )
        ws_scenario.overseer(*dispatch("PROJ-1", "--repo", "api", "--repo", "web", "--cursor", "ci=9"), code=2)
        refused = ws_scenario.overseer("ticket", "set", "PROJ-1", "--repo", "nope", "--phase", "ci_red", code=1)
        assert "'nope' is not a repository in this workspace (api, web)" in refused.err
        updated = ws_scenario.overseer(
            "ticket",
            "set",
            "PROJ-1",
            "--repo",
            "api",
            "--cursor",
            f"review={reviewed}",
            "--phase",
            "ci_red",
        )
        assert updated.out == "updated PROJ-1 (api)\n"
        [unit] = db.units(conn, "PROJ-1")
        assert (unit.repo, unit.phase, unit.review_cursor, unit.branch) == (
            "api",
            "ci_red",
            int(reviewed),
            None,
        )
        ticket = present(db.get_ticket(conn, "PROJ-1"))
        assert ticket.phase is None  # a phase about the PR is the unit's
        # The ticket's own phases are the ticket's, --repo or not.
        ws_scenario.overseer("ticket", "set", "PROJ-1", "--repo", "api", "--phase", "needs_human")
        ticket = present(db.get_ticket(conn, "PROJ-1"))
        assert ticket.phase == "needs_human"
        assert [u.phase for u in db.units(conn, "PROJ-1")] == ["ci_red"]
        # A phase about the PR with no --repo is its ticket's one unit's, and refused once the ticket has two.
        updated = ws_scenario.overseer("ticket", "set", "PROJ-1", "--phase", "approved")
        assert updated.out == "updated PROJ-1 (api)\n"
        ws_scenario.overseer("ticket", "set", "PROJ-1", "--repo", "web", "--phase", "ci_running")
        refused = ws_scenario.overseer("ticket", "set", "PROJ-1", "--phase", "merged", code=1)
        assert refused.err == (
            "Error: repo is required (--repo): the merged phase belongs to one unit, and PROJ-1 has units in api, web\n"
        )
        assert [(u.repo, u.phase) for u in db.units(conn, "PROJ-1")] == [("api", "approved"), ("web", "ci_running")]

        ws_scenario.overseer("attention", "PROJ-1", "needs_author", "--repo", "web", "--detail", PRS["web"])
        ws_scenario.overseer("attention", "PROJ-1", "needs_author", "--repo", "api", "--detail", PRS["api"])
        ws_scenario.overseer("attention", "PROJ-1", "multi_repo", "--detail", "api and web")
        ws_scenario.overseer("attention", "PROJ-1", "needs_author", "--repo", "nope", "--detail", "x", code=1)
    # Two units needing an author are two items: an item is its ticket, reason, and repository.
    assert [(i.subject, i.reason) for i in attention.current(conn)] == [
        ("PROJ-1", "multi_repo"),
        ("PROJ-1 (api)", "needs_author"),
        ("PROJ-1 (web)", "needs_author"),
    ]


def test_a_merge_conflict_is_a_units_phase(ws_scenario: Scenario) -> None:
    """A PR that conflicts with its base is `conflicted`, one unit's phase like the CI and review phases."""
    conn = ws_scenario.conn
    refused = ws_scenario.overseer("ticket", "set", "PROJ-1", "--phase", "conflicted", code=1)
    assert "repo is required (--repo): the conflicted phase belongs to one unit" in refused.err
    ws_scenario.overseer("ticket", "set", "PROJ-1", "--repo", "web", "--phase", "conflicted")
    [unit] = db.units(conn, "PROJ-1")
    assert (unit.repo, unit.phase) == ("web", "conflicted")
    ticket = present(db.get_ticket(conn, "PROJ-1"))
    assert ticket.phase is None


def test_untrusted_review_is_a_units_phase(ws_scenario: Scenario) -> None:
    """Feedback on a PR from an untrusted reviewer is `untrusted_review`, the unit's phase like `changes_requested`."""
    conn = ws_scenario.conn
    refused = ws_scenario.overseer("ticket", "set", "PROJ-1", "--phase", "untrusted_review", code=1)
    assert "repo is required (--repo): the untrusted_review phase belongs to one unit" in refused.err
    ws_scenario.overseer("ticket", "set", "PROJ-1", "--repo", "api", "--phase", "untrusted_review")
    [unit] = db.units(conn, "PROJ-1")
    assert (unit.repo, unit.phase) == ("api", "untrusted_review")
    ticket = present(db.get_ticket(conn, "PROJ-1"))
    assert ticket.phase is None


def test_a_units_phase_and_cursor_need_no_repo_in_a_workspace_of_one(scenario: Scenario) -> None:
    """A unit's phase or cursor that names no repository is the workspace's one repository's, unit or not."""
    conn = scenario.conn
    updated = scenario.overseer("ticket", "set", "PROJ-1", "--phase", "ci_red")
    assert updated.out == "updated PROJ-1 (repo)\n"
    [unit] = db.units(conn, "PROJ-1")
    assert (unit.repo, unit.phase) == ("repo", "ci_red")
    assert present(db.get_ticket(conn, "PROJ-1")).phase is None


def test_a_joint_prompt_override_without_the_repositories_is_refused(
    ws_scenario: Scenario,
    treehouse_state: Path,
) -> None:
    overrides = ws_scenario.env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text(
        "Work {{KEY}} in {{SLOT}} on {{BRANCH}} for {{LABELS}}\n{{DRAFTS}}\n",
    )
    [(action, reason)] = ws_scenario.refuses(dispatches(repo=("api", "web")))
    assert action == "refused:bad_prompt"
    assert reason.endswith("missing required placeholder {{REPOSITORIES}}, {{PRS}}")
    assert pool_statuses(treehouse_state) == ["available", "available"]
    # The same override still serves a run in one repository.
    alone = ws_scenario.run(dispatches(repo="api"))
    assert alone.prompt.startswith("Work PROJ-1 in ")


def test_a_killed_joint_run_is_detected_and_all_its_slots_returned(
    ws_scenario: Scenario,
    ws: Ws,
    treehouse_state: Path,
) -> None:
    """M7 acceptance, against the fakes: a joint run killed mid-way is found by the next tick, every slot returned."""
    working = ws_scenario.starts(dispatches(repo=("api", "web")))
    worker_pid = int(working.row["worker_pid"])
    desk = ws.root / "desks" / "PROJ-1"
    assert sorted(p.name for p in desk.iterdir()) == [desks.MARKER, "api", "web"]
    # A desk some earlier run left behind, with no run of its ticket running.
    stale = desks.make(ws.root, "PROJ-9", [("api", ws.clone("api"))])
    working.dies()
    assert pool_statuses(treehouse_state) == ["leased", "leased"]

    ticked = ws_scenario.tick(*waits("PROJ-1"))
    assert ticked.actions[0] == "attention:crashed"
    assert working.row["status"] == "crashed"
    deadline = time.monotonic() + 30
    while procs.alive(worker_pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not procs.alive(worker_pid)
    assert pool_statuses(treehouse_state) == ["available", "available"]
    assert not desk.exists()
    assert not stale.exists()
    assert ws.clone("api").is_dir()  # removing a desk never follows its links
    assert ws_scenario.attention() == [("PROJ-1", "crashed")]


def test_desks_are_made_only_in_a_directory_canopy_owns(ws: Ws, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (ws.root / "desks").symlink_to(elsewhere)
    with pytest.raises(desks.DeskError, match="is a symlink"):
        desks.make(ws.root, "PROJ-1", [("api", ws.clone("api"))])
    assert list(elsewhere.iterdir()) == []
    assert desks.prune(ws.root, []) == []


def test_canopy_removes_only_the_desks_it_made(ws: Ws) -> None:
    """Anything else under `desks/`, a directory named for a ticket included, is the operator's."""
    parent = ws.root / "desks"
    (parent / "notes").mkdir(parents=True)
    (parent / "notes" / "todo.md").write_text("mine\n")
    (parent / "README").write_text("mine\n")
    (parent / "PROJ-2").mkdir()
    (parent / "PROJ-2" / "plan.md").write_text("mine\n")
    (parent / "PROJ-3").symlink_to(ws.clone("web"), target_is_directory=True)
    stale = desks.make(ws.root, "PROJ-9", [("api", ws.clone("api"))])

    assert desks.prune(ws.root, []) == [stale]
    assert sorted(p.name for p in parent.iterdir()) == ["PROJ-2", "PROJ-3", "README", "notes"]
    for key in ("PROJ-2", "PROJ-3"):
        with pytest.raises(desks.DeskError, match="canopy did not make it"):
            desks.make(ws.root, key, [("api", ws.clone("api"))])
        assert not desks.remove(desks.path(ws.root, key))
    assert (parent / "PROJ-2" / "plan.md").read_text() == "mine\n"
    assert (parent / "PROJ-3").resolve() == ws.clone("web").resolve()


def test_a_joint_run_refuses_a_workspace_that_defines_canopys_agents(
    ws_scenario: Scenario,
    ws: Ws,
    treehouse_state: Path,
) -> None:
    # The desk is not a repository, so OpenCode may read config above it: the workspace root is checked (D044).
    (ws.root / ".opencode" / "agent").mkdir(parents=True)
    (ws.root / ".opencode" / "agent" / "canopy-worker.md").write_text("---\npermission:\n  bash: allow\n---\n")
    run = ws_scenario.run(dispatches(repo=("api", "web")))
    assert run.status == "crashed"
    assert "defines one of canopy's agents" in json.loads(run.row["result_json"])["harness"]
    assert not ws_scenario.agent_log.exists()  # the worker never started
    assert pool_statuses(treehouse_state) == ["available", "available"]
    assert not (ws.root / "desks" / "PROJ-1").exists()
