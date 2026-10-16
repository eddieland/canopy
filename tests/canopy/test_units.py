"""Units and joint runs (DESIGN §18, ROADMAP M7): a ticket's work per repository, desks, and all-or-nothing leases."""

import json
import os
import signal
import sqlite3
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import db
from canopy.core.vocab import RunStatus, TickStatus
from canopy.infra import lock, procs
from canopy.loop import attention
from canopy.runs import desks
from canopy.runs.dispatch import DISPATCH_LOCK
from tests.canopy.conftest import Ws, seed_pools
from tests.canopy.helpers import (
    InlineRunner,
    decisions,
    in_tick,
    overseer_does,
    wait_for_run,
    waits,
    worker_does,
)
from tests.conftest import CanopyEnv, git

LABEL = "agent-ready-tester"
BRANCH = "agent/PROJ-1-work"
PRS = {"api": "https://x.test/api/pull/1", "web": "https://x.test/web/pull/2", "docs": "https://x.test/docs/pull/3"}


def dispatch(key: str, *args: str, kind: str = "implement") -> list[str]:
    return ["dispatch", key, "--label", LABEL, "--kind", kind, *args]


def push_in(repo: str, message: str = "PROJ-1: the change") -> list[list[str]]:
    """Commands a worker in a desk runs to commit and push in one repository, through its link."""
    return [
        ["git", "-C", repo, "commit", "--quiet", "--allow-empty", "-m", message],
        ["git", "-C", repo, "push", "--quiet", "origin", f"HEAD:refs/heads/{BRANCH}"],
    ]


def done(prs: dict[str, str]) -> str:
    return json.dumps({"status": "done", "branch": BRANCH, "prs": prs, "summary": "changed both"})


def slots_of(conn: sqlite3.Connection, run_id: int) -> dict[str, Path]:
    return {str(s["repo"]): Path(s["slot_path"]) for s in db.run_slots(conn, run_id)}


def pool_statuses(treehouse_state: Path) -> list[str]:
    pools: dict[str, dict[str, list[dict[str, str]]]] = json.loads(treehouse_state.read_text())["pools"]
    return [s["status"] for p in pools.values() for s in p["slots"]]


def test_a_joint_implement_works_in_a_desk_and_opens_a_pr_per_repository(
    ws: Ws, treehouse_state: Path, agent_log: Path
) -> None:
    """M7 acceptance, against the fakes: one run over two repositories pushes both and records both PRs."""
    seed_pools(ws, treehouse_state)
    conn = ws.journal()
    with (
        in_tick(conn) as tick_id,
        worker_does(["readlink", "api"], *push_in("api"), *push_in("web"), result=done(PRS)),
    ):
        assert main(dispatch("PROJ-1", "--repo", "api", "--repo", "web", "--repo", "api")) == 0
        run = wait_for_run(conn, 1)
        assert run["status"] == "done", Path(run["log_path"]).read_text()

        # One run, one slot in each repository's pool, and the worker in a desk linking them.
        slots = slots_of(conn, 1)
        assert list(slots) == ["api", "web"]
        desk = ws.root / "desks" / "PROJ-1"
        [worker] = [json.loads(line) for line in agent_log.read_text().splitlines()]
        assert worker["cwd"] == str(desk)
        assert [c["returncode"] for c in worker["commands"]] == [0, 0, 0, 0, 0]
        assert worker["commands"][0]["stdout"].strip() == os.path.relpath(slots["api"], desk)
        assert not desk.exists()  # removed when the run ended
        assert pool_statuses(treehouse_state) == ["available", "available"]

        for name in ("api", "web"):
            assert ws.remote_head(name, BRANCH) == git("rev-parse", "HEAD", cwd=slots[name])
        # Each unit has the ticket's branch and its own PR; a PR for a repository the run was not in is not recorded.
        units = {u["repo"]: u for u in db.units(conn, "PROJ-1")}
        assert {r: (u["branch"], u["pr_url"]) for r, u in units.items()} == {
            "api": (BRANCH, PRS["api"]),
            "web": (BRANCH, PRS["web"]),
        }
        assert json.loads(run["result_json"])["prs"] == {"api": PRS["api"], "web": PRS["web"]}
        [(action, rationale)] = decisions(conn, tick_id)
        assert action == "dispatch:implement"
        assert (
            rationale == f"run 1: {BRANCH} in api at {slots['api']}, web at {slots['web']}; desk {desk}; label {LABEL}"
        )

        prompt = (ws.state_dir / "runs" / "1.prompt").read_text()
        assert f"ticket PROJ-1 in {desk}." in prompt
        assert "This is a joint run over 2 repositories" in prompt
        assert f"- `api` at `{desk / 'api'}`: branch `{BRANCH}` from `main`; PR: not recorded;" in prompt
        assert f"- `web` at `{desk / 'web'}`: branch `{BRANCH}` from `main`; PR: not recorded;" in prompt
        assert "Each PR's body links its sibling PRs and says which one merges first." in prompt
        assert '"prs":{"api":"<url or null>","web":"<url or null>"}' in prompt

        # The next run is told each unit's PR.
        db.finish_tick(conn, tick_id, TickStatus.OK, "test")
        with in_tick(conn):
            assert main(dispatch("PROJ-1", "--repo", "web", "--repo", "api", kind="resume"), runner=InlineRunner()) == 0
            prompt = (ws.state_dir / "runs" / "2.prompt").read_text()
            assert f"- `web` at `{desk / 'web'}`: branch `{BRANCH}` from `main`; PR: {PRS['web']}." in prompt


def test_leases_are_all_or_nothing(ws: Ws, treehouse_state: Path, capsys: pytest.CaptureFixture[str]) -> None:
    seed_pools(ws, treehouse_state)
    state = json.loads(treehouse_state.read_text())
    state["pools"][str(ws.clone("web"))].update(max_trees=1, slots=[{"name": "1", "path": "/busy", "status": "in-use"}])
    treehouse_state.write_text(json.dumps(state))
    conn = ws.journal()
    with in_tick(conn) as tick_id:
        runner = InlineRunner()

        assert main(dispatch("PROJ-1", "--repo", "api", "--repo", "web"), runner=runner) == 1
        assert "dispatch refused (no_slot): web: treehouse get exited 1: " in capsys.readouterr().err
        assert [a for a, _ in decisions(conn, tick_id)] == ["refused:no_slot"]
        # api's slot was leased first, and returned before the refusal was recorded.
        assert pool_statuses(treehouse_state) == ["available", "in-use"]
        calls: list[list[str]] = json.loads(treehouse_state.read_text())["calls"]
        assert [c[0] for c in calls] == ["get", "get", "return"]
        assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
        assert runner.spawned == []


def test_a_joint_run_is_unpushed_if_any_repository_is(ws: Ws, treehouse_state: Path, agent_log: Path) -> None:
    seed_pools(ws, treehouse_state)
    hook = ws.origins["web"] / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'push refused by test hook' >&2\nexit 1\n")
    hook.chmod(0o755)
    conn = ws.journal()
    with in_tick(conn), worker_does(*push_in("api"), *push_in("web"), result=done({"api": PRS["api"]})):
        assert main(dispatch("PROJ-1", "--repo", "api", "--repo", "web")) == 0
        run = wait_for_run(conn, 1)

        assert run["status"] == "unpushed"
        note = json.loads(run["result_json"])["harness"]
        assert note.startswith(f"web: commits on {BRANCH} are not on origin; the push failed: ")
        assert "api" not in note.split(":", 1)[1]  # api's branch is pushed, so only web is named
        assert ws.remote_head("api", BRANCH) is not None
        assert pool_statuses(treehouse_state) == ["available", "available"]
        [item] = attention.from_runs(conn)
        assert (item.ticket_key, item.reason) == ("PROJ-1", "unpushed")


def test_units_have_their_own_attempts_and_share_the_branch(ws: Ws, treehouse_state: Path) -> None:
    seed_pools(ws, treehouse_state)
    conn = ws.journal()
    with in_tick(conn) as tick_id:
        runner = InlineRunner()

        def run(*args: str, kind: str = "implement") -> int:
            code = main(dispatch("PROJ-1", *args, kind=kind), runner=runner)
            if code == 0:
                run_id = int(conn.execute("SELECT max(id) FROM runs").fetchone()[0])
                for s in db.run_slots(conn, run_id):  # as `_run` would when the worker is done
                    assert runner.run(
                        ["treehouse", "return", "--force", s["slot_path"]], env={"TREEHOUSE_ROOT": str(ws.root)}
                    ).ok
                assert db.finish_run(conn, "runs", run_id, RunStatus.DONE, "{}")
            return code

        assert run("--repo", "api", "--slug", "login") == 0
        # The first implement named the branch; a later one adds a unit on the same branch, and may not rename it.
        assert run("--repo", "web", "--slug", "other") == 1
        assert run("--repo", "web", "--slug", "login") == 0
        assert run("--repo", "api", kind="fix-ci") == 0
        assert run("--repo", "api") == 0  # api's second implement: its limit is 2
        assert run("--repo", "api", "--repo", "web") == 1
        assert run("--repo", "web") == 0  # web has had one

        assert [a for a, _ in decisions(conn, tick_id)] == [
            "dispatch:implement",
            "refused:bad_slug",
            "dispatch:implement",
            "dispatch:fix-ci",
            "dispatch:implement",
            "refused:attempt_limit",
            "attention:attempt_limit",
            "dispatch:implement",
        ]
        reasons = dict(decisions(conn, tick_id))
        assert reasons["refused:bad_slug"] == (
            "PROJ-1's branch is agent/PROJ-1-login, named by its first implement; leave out --slug"
        )
        assert reasons["refused:attempt_limit"] == "PROJ-1 in api has had 2 implement runs and the limit is 2"
        [limit] = [d for d in db.decisions_for_tick(conn, tick_id) if d.action == "attention:attempt_limit"]
        assert limit.repo == "api"  # the item is about the unit at its limit
        assert {str(r["branch"]) for r in conn.execute("SELECT branch FROM runs")} == {"agent/PROJ-1-login"}

        # fix-ci's cooldown is per unit too: api's just ended, web has had none.
        assert main(dispatch("PROJ-1", "--repo", "api", kind="fix-ci"), runner=runner) == 1
        assert decisions(conn, tick_id)[-1][0] == "refused:cooldown"
        assert run("--repo", "web", kind="fix-ci") == 0


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
                "PROJ-1's branch is agent/PROJ-1-login, named by its first implement; leave out --slug",
            )
        ]


def test_the_state_block_shows_each_unit(ws: Ws, treehouse_state: Path, agent_log: Path) -> None:
    seed_pools(ws, treehouse_state)
    conn = ws.journal()
    with worker_does(*push_in("api"), *push_in("web"), result=done(PRS)):
        with in_tick(conn):
            assert main(dispatch("PROJ-1", "--repo", "api", "--repo", "web")) == 0
            wait_for_run(conn, 1)
            assert main(["ticket", "set", "PROJ-1", "--repo", "web", "--phase", "ci_red", "--cursor", "ci=run-9"]) == 0
            assert main(["ticket", "set", "PROJ-1", "--phase", "running", "--cursor", "comment=c-1"]) == 0
        with overseer_does(*waits("PROJ-1")):
            assert main(["tick", "--dry-run"]) == 0

    overseer = json.loads(agent_log.read_text().splitlines()[-1])
    state = json.loads(overseer["argv"][3].split("```json\n", 1)[1].split("\n```", 1)[0])
    [ticket] = state["tickets"]
    assert (ticket["phase"], ticket["branch"], ticket["cursors"]) == (
        "running",
        BRANCH,
        {"comment": "c-1", "message": None, "mirror": None},
    )
    no_limit = {"implement": 1, "fix-ci": 0, "resume": 0}
    assert ticket["units"] == [
        {
            "repo": "api",
            "branch": BRANCH,
            "pr_url": PRS["api"],
            "phase": None,
            "cursors": {"review": None, "ci": None},
            "attempts": no_limit,
            "fix_ci_cooldown_until": None,
        },
        {
            "repo": "web",
            "branch": BRANCH,
            "pr_url": PRS["web"],
            "phase": "ci_red",
            "cursors": {"review": None, "ci": "run-9"},
            "attempts": no_limit,
            "fix_ci_cooldown_until": None,
        },
    ]
    assert ticket["last_run"]["repos"] == [{"repo": "api", "base": "main"}, {"repo": "web", "base": "main"}]


def test_journal_commands_name_a_unit(ws: Ws, capsys: pytest.CaptureFixture[str]) -> None:
    conn = ws.journal()
    with in_tick(conn) as tick_id:
        # A review or ci cursor is a unit's: in a workspace of several it needs --repo, and one repository.
        reviewed = "2026-10-07T20:58:50Z"
        assert main(["ticket", "set", "PROJ-1", "--cursor", f"review={reviewed}"]) == 2
        assert "a review cursor belongs to one unit: name its repository with --repo" in capsys.readouterr().err
        assert main(dispatch("PROJ-1", "--repo", "api", "--repo", "web", "--cursor", "ci=9")) == 2
        assert main(["ticket", "set", "PROJ-1", "--repo", "nope", "--phase", "ci_red"]) == 1
        assert "'nope' is not a repository in this workspace (api, web)" in capsys.readouterr().err
        assert (
            main(["ticket", "set", "PROJ-1", "--repo", "api", "--cursor", f"review={reviewed}", "--phase", "ci_red"])
            == 0
        )
        assert capsys.readouterr().out == "updated PROJ-1 (api)\n"
        [unit] = db.units(conn, "PROJ-1")
        assert (unit["repo"], unit["phase"], unit["last_review_id"], unit["branch"]) == (
            "api",
            "ci_red",
            reviewed,
            None,
        )
        ticket = db.get_ticket(conn, "PROJ-1")
        assert ticket is not None
        assert ticket.phase is None  # a phase about the PR is the unit's
        # A phase about the PR needs its unit; the ticket's own phases are the ticket's, --repo or not.
        assert main(["ticket", "set", "PROJ-1", "--phase", "approved"]) == 2
        assert "the approved phase belongs to one unit: name its repository with --repo" in capsys.readouterr().err
        assert main(["ticket", "set", "PROJ-1", "--repo", "api", "--phase", "needs_human"]) == 0
        capsys.readouterr()
        ticket = db.get_ticket(conn, "PROJ-1")
        assert ticket is not None
        assert ticket.phase == "needs_human"
        assert [u["phase"] for u in db.units(conn, "PROJ-1")] == ["ci_red"]

        assert (
            main(["attention", "PROJ-1", "needs_author", "--repo", "web", "--detail", "https://x.test/web/pull/2"]) == 0
        )
        assert (
            main(["attention", "PROJ-1", "needs_author", "--repo", "api", "--detail", "https://x.test/api/pull/1"]) == 0
        )
        assert main(["attention", "PROJ-1", "multi_repo", "--detail", "api and web"]) == 0
        assert main(["attention", "PROJ-1", "needs_author", "--repo", "nope", "--detail", "x"]) == 1
        db.finish_tick(conn, tick_id, TickStatus.OK, "test")
        # Two units needing an author are two items: an item is its ticket, reason, and repository.
        assert [(i.subject, i.reason) for i in attention.current(conn)] == [
            ("PROJ-1", "multi_repo"),
            ("PROJ-1 (api)", "needs_author"),
            ("PROJ-1 (web)", "needs_author"),
        ]


def test_a_merge_conflict_is_a_units_phase(ws: Ws, capsys: pytest.CaptureFixture[str]) -> None:
    """A PR that conflicts with its base is `conflicted`, one unit's phase like the CI and review phases."""
    conn = ws.journal()
    with in_tick(conn):
        assert main(["ticket", "set", "PROJ-1", "--phase", "conflicted"]) == 2
        assert "the conflicted phase belongs to one unit: name its repository with --repo" in capsys.readouterr().err
        assert main(["ticket", "set", "PROJ-1", "--repo", "web", "--phase", "conflicted"]) == 0
        [unit] = db.units(conn, "PROJ-1")
        assert (unit["repo"], unit["phase"]) == ("web", "conflicted")
        ticket = db.get_ticket(conn, "PROJ-1")
        assert ticket is not None
        assert ticket.phase is None


def test_untrusted_review_is_a_units_phase(ws: Ws, capsys: pytest.CaptureFixture[str]) -> None:
    """Feedback on a PR from an untrusted reviewer is `untrusted_review`, the unit's phase like `changes_requested`."""
    conn = ws.journal()
    with in_tick(conn):
        assert main(["ticket", "set", "PROJ-1", "--phase", "untrusted_review"]) == 2
        err = capsys.readouterr().err
        assert "the untrusted_review phase belongs to one unit: name its repository with --repo" in err
        assert main(["ticket", "set", "PROJ-1", "--repo", "api", "--phase", "untrusted_review"]) == 0
    [unit] = db.units(conn, "PROJ-1")
    assert (unit["repo"], unit["phase"]) == ("api", "untrusted_review")
    ticket = db.get_ticket(conn, "PROJ-1")
    assert ticket is not None
    assert ticket.phase is None


def test_a_joint_prompt_override_without_the_repositories_is_refused(
    ws: Ws, canopy_env: CanopyEnv, treehouse_state: Path
) -> None:
    seed_pools(ws, treehouse_state)
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text("Work {{KEY}} in {{SLOT}} on {{BRANCH}} for {{LABELS}}\n")
    conn = ws.journal()
    with in_tick(conn) as tick_id:
        runner = InlineRunner()
        assert main(dispatch("PROJ-1", "--repo", "api", "--repo", "web"), runner=runner) == 1
        [(action, reason)] = decisions(conn, tick_id)
        assert action == "refused:bad_prompt"
        assert reason.endswith("missing required placeholder {{REPOSITORIES}}, {{PRS}}")
        assert pool_statuses(treehouse_state) == ["available", "available"]
        # The same override still serves a run in one repository.
        assert main(dispatch("PROJ-1", "--repo", "api"), runner=runner) == 0


def test_a_killed_joint_run_is_detected_and_all_its_slots_returned(
    ws: Ws, treehouse_state: Path, agent_log: Path
) -> None:
    """M7 acceptance, against the fakes: a joint run killed mid-way is found by the next tick, every slot returned."""
    seed_pools(ws, treehouse_state)
    conn = ws.journal()
    with worker_does(), mock.patch.dict(os.environ, {"FAKE_WORKER_SLEEP": "60"}):
        with in_tick(conn) as tick_id:
            assert main(dispatch("PROJ-1", "--repo", "api", "--repo", "web")) == 0
            db.finish_tick(conn, tick_id, TickStatus.OK, "test")

        deadline = time.monotonic() + 30
        run = db.get_run(conn, 1)
        while (run is None or run["worker_pid"] is None or not agent_log.exists()) and time.monotonic() < deadline:
            time.sleep(0.05)
            run = db.get_run(conn, 1)
        assert run is not None
        assert run["worker_pid"] is not None, "`_run` never started the worker"
        pid, worker_pid = int(run["pid"]), int(run["worker_pid"])
        desk = ws.root / "desks" / "PROJ-1"
        assert sorted(p.name for p in desk.iterdir()) == [desks.MARKER, "api", "web"]
        # A desk some earlier run left behind, with no run of its ticket running.
        stale = desks.make(ws.root, "PROJ-9", [("api", ws.clone("api"))])
        os.kill(pid, signal.SIGKILL)
        while procs.alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert pool_statuses(treehouse_state) == ["leased", "leased"]

        with overseer_does(*waits("PROJ-1")):
            assert main(["tick"]) == 0
        crashed = db.get_run(conn, 1)
        assert crashed is not None
        assert crashed["status"] == "crashed"
        while procs.alive(worker_pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not procs.alive(worker_pid)
        assert pool_statuses(treehouse_state) == ["available", "available"]
        assert not desk.exists()
        assert not stale.exists()
        assert ws.clone("api").is_dir()  # removing a desk never follows its links
        assert [(i.ticket_key, i.reason) for i in attention.current(conn)] == [("PROJ-1", "crashed")]


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
    ws: Ws, treehouse_state: Path, agent_log: Path
) -> None:
    # The desk is not a repository, so OpenCode may read config above it: the workspace root is checked (D044).
    seed_pools(ws, treehouse_state)
    (ws.root / ".opencode" / "agent").mkdir(parents=True)
    (ws.root / ".opencode" / "agent" / "canopy-worker.md").write_text("---\npermission:\n  bash: allow\n---\n")
    conn = ws.journal()
    with in_tick(conn):
        assert main(dispatch("PROJ-1", "--repo", "api", "--repo", "web")) == 0
        run = wait_for_run(conn, 1)
        assert run["status"] == "crashed"
        assert "defines one of canopy's agents" in json.loads(run["result_json"])["harness"]
        assert not agent_log.exists()  # the worker never started
        assert pool_statuses(treehouse_state) == ["available", "available"]
        assert not (ws.root / "desks" / "PROJ-1").exists()
