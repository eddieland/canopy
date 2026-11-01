"""`canopy _run`: branch setup, the worker, result parsing, push verification, slot return (DESIGN §8).

Runs are played by the `scenario` fixture's `run`, which dispatches with an `InlineRunner`, spawning nothing, and then
runs the run in-process with `main(["_run", ...])`.
"""

import json
import os
import re
import signal
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import cards, config, db, definitions, prompts, run_models, workspace
from canopy.core.vocab import FlakyCause, RunStatus
from canopy.runs import worker
from canopy.runtime import servers
from canopy.runtime.implementation import Version
from tests.canopy.helpers import (
    InlineRunner,
    agent_runs,
    commit_and_push,
    has_deadline,
    inline_servers,
    pool,
    present,
    private_worker_does,
    scripted,
    slot_of,
    ticket_sets,
    tools_of,
    tools_printed,
    unit_of,
    with_events,
    worker_does,
)
from tests.canopy.scenario_helpers import Scenario, asks, dispatches, pushes
from tests.conftest import CanopyEnv, GitPool, git


def test_worker_that_pushes_is_done(scenario: Scenario, git_pool: GitPool, treehouse_state: Path) -> None:
    before = time.time()
    run = scenario.run(worker=pushes())
    after = time.time()

    assert run.status == "done"
    assert run.row["ended_at"] is not None
    assert json.loads(run.row["result_json"]) == {
        "status": "done",
        "branch": "agent/PROJ-1-work",
        "pr": "https://example.test/pr/1",
        "prs": {"repo": "https://example.test/pr/1"},  # a result from before joint runs is read as the new contract
        "pr_titles": None,  # nor did it report its PR's title
        "summary": "did it",
        "question": None,
        "flaky": False,
        "flaky_cause": None,
        "flaky_detail": None,
    }
    [w] = agent_runs(scenario.agent_log)
    assert w["cwd"] == slot_of(scenario.conn, run.id).slot_path
    # No CANOPY_TICK_ID: a worker cannot act as the overseer.
    # CANOPY_RUN_ID: the operator's commands refuse inside the run (DESIGN §22).
    # The snapshot made for the config and the prompt's fixed instructions (DESIGN §13).
    cfg = config.load(scenario.env.root)
    bodies, _ = definitions.run_prompt(run.prompt, cfg.runtime.worker_cmd)
    snapshot = definitions.ensure(scenario.env.state_dir, cfg, bodies=bodies)
    # CANOPY_GIT_OBJECTS: the run's object directory, for a sandbox wrapper (DESIGN §8).
    objects = scenario.env.state_dir / "runs" / f"{run.id}.objects"
    # CANOPY_DEADLINE: the moment its timeout fires, for the clock in the snapshot (DESIGN §33).
    assert has_deadline(w, 45, before=before, after=after)
    # canopy's `status` server, the one server of canopy's a worker is given (DESIGN §41).
    assert inline_servers(w) == {cards.SERVER: [*cards.SERVER_COMMAND]}
    assert w["env"] == {
        **{name: w["env"][name] for name in servers.VARIABLES},
        "CANOPY_RUN_ID": str(run.id),
        "CANOPY_GIT_OBJECTS": str(objects),
        # Where the operator's answer to a question its card asks reaches it (DESIGN §41).
        "CANOPY_ANSWERS": str(scenario.env.state_dir / "runs" / f"{run.id}.answers"),
        "CANOPY_DEADLINE": w["env"]["CANOPY_DEADLINE"],
        "OPENCODE_CONFIG_DIR": str(snapshot),
        # The trailers canopy's git hooks add to its commits (TRUST_MODEL T5).
        "CANOPY_COMMIT_TRAILERS": "Co-authored-by: canopy worker <noreply@canopy.invalid>",
    }
    assert not objects.exists()  # removed once the run was over
    argv = w["argv"]
    assert isinstance(argv, list)
    assert argv[:4] == ["run", "--agent", "canopy-worker", "--title=PROJ-1 implement"]
    assert argv[4] == prompts.split(run.prompt).message

    slot = Path(slot_of(scenario.conn, run.id).slot_path)
    # Detached: the worker pushed HEAD to the branch, which started from origin/main.
    assert git("rev-parse", "--abbrev-ref", "HEAD", cwd=slot) == "HEAD"
    assert git_pool.remote_head("agent/PROJ-1-work") == git("rev-parse", "HEAD", cwd=slot)
    assert git("rev-parse", "HEAD~1", cwd=slot) == git_pool.remote_head("main")
    assert all(s["status"] == "available" for s in pool(treehouse_state))
    assert unit_of(scenario.conn, "PROJ-1").pr_url == "https://example.test/pr/1"
    assert "run 1: done" in run.printed.out


@pytest.mark.usefixtures("git_pool")
def test_a_worker_inherits_no_server_its_process_was_given(scenario: Scenario) -> None:
    """A server of canopy's is given to one run alone (DESIGN §27): a run started below it does not inherit it."""
    given = servers.env({"canopy_chore": ["canopy", "_mcp", "--chore"]}, cwd=scenario.env.root, version=Version.ONE)
    with mock.patch.dict(os.environ, given):
        scenario.run(worker=pushes())
    [w] = agent_runs(scenario.agent_log)
    assert inline_servers(w).keys() == {cards.SERVER}


@pytest.mark.usefixtures("git_pool")
def test_a_worker_that_may_publish_is_given_its_runs_origin_for_the_store(scenario: Scenario) -> None:
    """canopy, not the worker, names the ticket an artifact is for (DESIGN §38): the store sets these pairs over its."""
    scenario.configures("private", artifacts={"mcp_server": "louvre", "publish_roles": ["worker"]})
    run = scenario.run(worker=pushes())
    [w] = agent_runs(scenario.agent_log)
    assert json.loads(w["env"]["CANOPY_ARTIFACT_ORIGIN"]) == {
        "canopy.workspace": workspace.load(scenario.env.root).name,
        "canopy.ticket": "PROJ-1",
        "canopy.run": str(run.id),
    }


@pytest.mark.usefixtures("git_pool")
def test_a_worker_config_does_not_let_publish_is_given_no_origin(scenario: Scenario) -> None:
    scenario.configures("private", artifacts={"mcp_server": "louvre", "publish_roles": []})
    scenario.run(worker=pushes())
    [w] = agent_runs(scenario.agent_log)
    assert "CANOPY_ARTIFACT_ORIGIN" not in w["env"]


@pytest.mark.usefixtures("git_pool")
def test_a_private_tickets_worker_is_given_no_origin(scenario: Scenario) -> None:
    """A private ticket's worker never publishes (DESIGN §22), so it is given nothing to name its ticket to a store."""
    scenario.configures("private", artifacts={"mcp_server": "louvre", "publish_roles": ["worker"]})
    scenario.operator("start", "PROJ-1")
    done: dict[str, object] = {"status": "done", "summary": "did it"}
    run = scenario.run(
        dispatches(label=None),
        worker=private_worker_does(*commit_and_push("agent/PROJ-1-work"), result=done),
    )
    assert run.row["private"] == 1
    [w] = agent_runs(scenario.agent_log)
    assert "CANOPY_ARTIFACT_ORIGIN" not in w["env"]


@pytest.mark.parametrize(
    ("title", "session_title"),
    [(None, "PROJ-1 implement"), ("Fix the\nlogin loop\x1b[2J", "PROJ-1 implement: Fix the login loop [2J")],
)
def test_the_session_title_names_the_ticket_and_its_title(
    scenario: Scenario,
    git_pool: GitPool,
    title: str | None,
    session_title: str,
) -> None:
    """`{title}` is the run's session title, so the runtime's session list names the ticket (DESIGN §13)."""
    template = "env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-worker --title={title} {prompt}"
    scenario.configures(runtime={"worker_cmd": template})
    if title is not None:
        scenario.overseer(ticket_sets("PROJ-1", title=title))
    scenario.run(worker=pushes())
    [w] = agent_runs(scenario.agent_log)
    argv = w["argv"]
    assert isinstance(argv, list)
    assert argv[3] == f"--title={session_title}"


def test_a_worker_template_that_places_no_prompt_gets_it_on_stdin(scenario: Scenario, git_pool: GitPool) -> None:
    """No argument limit applies to a prompt on stdin (D023), and the suffix still follows the template's words."""
    scenario.configures(
        runtime={
            "worker_cmd": "env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-worker",
            "worker_cmd_suffix": "--log-level INFO",
        },
    )
    run = scenario.run(worker=pushes())
    assert run.status == "done"
    [w] = agent_runs(scenario.agent_log)
    assert w["argv"] == ["run", "--agent", "canopy-worker", "--log-level", "INFO"]
    assert w["stdin"] == prompts.split(run.prompt).message


def test_the_worker_runs_between_the_prefix_and_the_suffix(scenario: Scenario, git_pool: GitPool) -> None:
    """One prefix and suffix wrap every command a worker run starts, such as a sandbox wrapper (DESIGN §12)."""
    scenario.configures(
        runtime={"worker_cmd_prefix": "env CANOPY_WRAPPED={title}", "worker_cmd_suffix": "--log-level INFO"},
    )
    run = scenario.run(worker=pushes())
    assert run.status == "done"
    [w] = agent_runs(scenario.agent_log)
    assert w["env"]["CANOPY_WRAPPED"] == "PROJ-1 implement"
    assert w["argv"][-2:] == ["--log-level", "INFO"]


def test_a_run_makes_no_local_branch(scenario: Scenario, git_pool: GitPool) -> None:
    """A pool's slots share its branch refs, so a worker starts detached, and a bare push has nowhere to go."""
    run = scenario.run(
        worker=worker_does(
            ["git", "symbolic-ref", "--quiet", "HEAD"],
            ["git", "for-each-ref", "--format=%(refname)", "refs/heads/agent/"],
            ["git", "commit", "--quiet", "--allow-empty", "-m", "PROJ-1: work"],
            ["git", "push", "--quiet", "origin"],
        ),
    )
    [w] = agent_runs(scenario.agent_log)
    commands = w["commands"]
    assert isinstance(commands, list)
    assert commands[0]["returncode"] == 1  # detached
    assert commands[1]["stdout"] == ""
    assert commands[3]["returncode"] != 0  # not on a branch: nothing a bare push could target, the base included
    slot = Path(slot_of(scenario.conn, run.id).slot_path)
    assert git_pool.remote_head("main") == git("rev-parse", "HEAD~1", cwd=slot)


def test_unpushed_commits_are_pushed_once(scenario: Scenario, git_pool: GitPool) -> None:
    run = scenario.run(
        worker=worker_does(["git", "commit", "--quiet", "--allow-empty", "-m", "PROJ-1: forgot to push"]),
    )
    assert run.status == "done"
    slot = Path(slot_of(scenario.conn, run.id).slot_path)
    assert git_pool.remote_head("agent/PROJ-1-work") == git("rev-parse", "HEAD", cwd=slot)


def test_commits_the_worker_moved_head_off_are_unpushed(scenario: Scenario, git_pool: GitPool) -> None:
    """Detached, HEAD alone holds the worker's commits: checking out something else leaves them behind."""
    run = scenario.run(
        worker=worker_does(
            ["git", "commit", "--quiet", "--allow-empty", "-m", "PROJ-1: left behind"],
            ["git", "checkout", "--quiet", "--detach", "origin/main"],
        ),
    )
    assert run.status == "unpushed"
    assert "the worker moved HEAD off 1 commit(s) not on origin" in json.loads(run.row["result_json"])["harness"]
    assert git_pool.remote_head("agent/PROJ-1-work") is None


def test_a_worker_that_pushed_and_then_moved_head_is_done(scenario: Scenario, git_pool: GitPool) -> None:
    moves = ["git", "checkout", "--quiet", "--detach", "origin/main"]
    run = scenario.run(worker=worker_does(*commit_and_push("agent/PROJ-1-work"), moves))
    assert run.status == "done"
    assert git_pool.remote_head("agent/PROJ-1-work") != git_pool.remote_head("main")


def branch_behind_main(git_pool: GitPool, branch: str = "agent/PROJ-1-work") -> None:
    """Put `branch` on origin with two commits of its own, and then a commit on `main` it lacks."""
    seed = git_pool.slots[1]
    git("checkout", "--quiet", "-b", branch, "origin/main", cwd=seed)
    for name in ("a", "b"):
        (seed / f"{name}.txt").write_text(f"{name}\n")
        git("add", f"{name}.txt", cwd=seed)
        git("commit", "--quiet", "-m", f"PROJ-1: {name}", cwd=seed)
    git("push", "--quiet", "origin", branch, cwd=seed)
    git("checkout", "--quiet", "--detach", "origin/main", cwd=seed)
    (seed / "m.txt").write_text("m\n")
    git("add", "m.txt", cwd=seed)
    git("commit", "--quiet", "-m", "main moves on", cwd=seed)
    git("push", "--quiet", "origin", "HEAD:refs/heads/main", cwd=seed)
    git("checkout", "--quiet", "--detach", cwd=seed)


def commit_file(name: str) -> list[str]:
    return ["sh", "-c", f"echo {name} > {name}.txt && git add {name}.txt && git commit --quiet -m 'PROJ-1: {name}'"]


def test_a_rebase_dropped_for_the_same_work_pushed_another_way_is_done(scenario: Scenario, git_pool: GitPool) -> None:
    """Issue #293: the worker rebased, could not force-push, and pushed a fix on top of origin's branch instead."""
    branch_behind_main(git_pool)
    run = scenario.run(
        worker=worker_does(
            ["git", "rebase", "--quiet", "origin/main"],
            ["git", "checkout", "--quiet", "--detach", "origin/agent/PROJ-1-work"],
            commit_file("fix"),
            ["git", "push", "--quiet", "origin", "HEAD:refs/heads/agent/PROJ-1-work"],
        ),
    )
    assert run.status == "done", run.row["result_json"]
    slot = Path(slot_of(scenario.conn, run.id).slot_path)
    assert git_pool.remote_head("agent/PROJ-1-work") == git("rev-parse", "HEAD", cwd=slot)


def test_a_rebase_dropped_with_work_of_its_own_is_unpushed(scenario: Scenario, git_pool: GitPool) -> None:
    """Only a commit whose change origin already has is dropped from the check: new work left behind still counts."""
    branch_behind_main(git_pool)
    run = scenario.run(
        worker=worker_does(
            ["git", "rebase", "--quiet", "origin/main"],
            commit_file("lost"),
            ["git", "checkout", "--quiet", "--detach", "origin/agent/PROJ-1-work"],
            commit_file("fix"),
            ["git", "push", "--quiet", "origin", "HEAD:refs/heads/agent/PROJ-1-work"],
        ),
    )
    assert run.status == "unpushed"
    assert "the worker moved HEAD off 1 commit(s) not on origin" in json.loads(run.row["result_json"])["harness"]


def test_a_rebase_aborted_and_made_again_leaves_nothing_behind(scenario: Scenario, git_pool: GitPool) -> None:
    """A copy the aborted attempt made is left behind, with the same patch as one the second attempt pushed.

    `fix` changed the copy's file since, so merging the copy into origin's branch conflicts.
    """
    scenario.configures(trust={"rebase": True})
    branch_behind_main(git_pool)
    # Dated, so the first attempt's copy is not the commit the second makes.
    first = "GIT_COMMITTER_DATE=2001-01-01T00:00:00 git rebase --quiet --exec false origin/main; git rebase --abort"
    run = scenario.run(
        worker=worker_does(
            ["sh", "-c", "echo fix > a.txt && git commit --quiet -am 'PROJ-1: fix'"],
            ["sh", "-c", first],
            ["git", "rebase", "--quiet", "origin/main"],
            ["git", "push", "--quiet", "--force-with-lease", "origin", "HEAD:refs/heads/agent/PROJ-1-work"],
        ),
    )
    assert run.status == "done", run.row["result_json"]
    slot = Path(slot_of(scenario.conn, run.id).slot_path)
    assert git_pool.remote_head("agent/PROJ-1-work") == git("rev-parse", "HEAD", cwd=slot)


def test_without_rebase_a_rebased_branch_is_never_forced(scenario: Scenario, git_pool: GitPool) -> None:
    branch_behind_main(git_pool)
    before = git_pool.remote_head("agent/PROJ-1-work")
    run = scenario.run(worker=worker_does(["git", "rebase", "--quiet", "origin/main"]))
    assert run.status == "unpushed"
    assert "not on origin; the push failed: " in json.loads(run.row["result_json"])["harness"]
    assert git_pool.remote_head("agent/PROJ-1-work") == before


def test_with_rebase_a_worker_that_rebased_and_pushed_with_a_lease_is_done(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    """Its own commit, made before the rebase, and origin's old commits are replaced by copies: nothing is lost."""
    scenario.configures(trust={"rebase": True})
    branch_behind_main(git_pool)
    run = scenario.run(
        worker=worker_does(
            commit_file("fix"),
            ["git", "rebase", "--quiet", "origin/main"],
            ["git", "push", "--quiet", "--force-with-lease", "origin", "HEAD:refs/heads/agent/PROJ-1-work"],
        ),
    )
    assert run.status == "done", run.row["result_json"]
    slot = Path(slot_of(scenario.conn, run.id).slot_path)
    assert git_pool.remote_head("agent/PROJ-1-work") == git("rev-parse", "HEAD", cwd=slot)
    assert git("merge-base", "--is-ancestor", "origin/main", "HEAD", cwd=slot) == ""


def test_with_rebase_canopy_pushes_a_rebased_branch_with_a_lease(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures(trust={"rebase": True})
    branch_behind_main(git_pool)
    run = scenario.run(worker=worker_does(["git", "rebase", "--quiet", "origin/main"]))
    assert run.status == "done", run.row["result_json"]
    slot = Path(slot_of(scenario.conn, run.id).slot_path)
    assert git_pool.remote_head("agent/PROJ-1-work") == git("rev-parse", "HEAD", cwd=slot)


def test_with_rebase_canopy_never_overwrites_a_push_made_since_the_run_started(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    scenario.configures(trust={"rebase": True})
    branch_behind_main(git_pool)
    other = git_pool.slots[1]
    script = (
        f"git -C {other} fetch --quiet origin && git -C {other} checkout --quiet --detach origin/agent/PROJ-1-work && "
        f"git -C {other} commit --quiet --allow-empty -m 'a coworker' && "
        f"git -C {other} push --quiet origin HEAD:refs/heads/agent/PROJ-1-work"
    )
    pushed_meanwhile = ["sh", "-c", script]
    run = scenario.run(worker=worker_does(pushed_meanwhile, ["git", "rebase", "--quiet", "origin/main"]))
    assert run.status == "unpushed"
    assert "not on origin; the push failed: " in json.loads(run.row["result_json"])["harness"]
    assert git("log", "-1", "--format=%s", git_pool.remote_head("agent/PROJ-1-work") or "", cwd=other) == "a coworker"


@pytest.mark.parametrize("only_here", [False, True])
def test_a_local_branch_an_earlier_canopy_left_is_dropped_unless_it_holds_commits_origin_lacks(
    scenario: Scenario,
    git_pool: GitPool,
    only_here: bool,  # noqa: FBT001  (a parameter of the test)
) -> None:
    """Before D109 a run made its branch locally with `checkout -B`, and the pool's repository still has it."""
    for slot in git_pool.slots:
        git("branch", "agent/PROJ-1-work", "origin/main", cwd=slot)
        if only_here:
            stray = git("commit-tree", "-m", "only here", "-p", "origin/main", "origin/main^{tree}", cwd=slot)
            git("branch", "--force", "agent/PROJ-1-work", stray, cwd=slot)
    run = scenario.run(worker=pushes())
    assert run.status == "done"
    slot = Path(slot_of(scenario.conn, run.id).slot_path)
    left = git("for-each-ref", "--format=%(refname)", "refs/heads/agent/PROJ-1-work", cwd=slot)
    assert left == ("refs/heads/agent/PROJ-1-work" if only_here else "")


def test_failed_push_is_unpushed(scenario: Scenario, git_pool: GitPool, treehouse_state: Path) -> None:
    git_pool.reject_pushes()
    run = scenario.run(worker=pushes())
    assert run.status == "unpushed"
    result = json.loads(run.row["result_json"])
    assert result["status"] == "done"  # what the worker claimed is kept
    assert "not on origin; the push failed: " in result["harness"]
    assert "push refused by test hook" in result["harness"]
    assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_no_commits_is_not_unpushed(scenario: Scenario, git_pool: GitPool) -> None:
    run = scenario.run(worker=asks("which API?"))
    assert run.status == "blocked"
    assert json.loads(run.row["result_json"])["question"] == "which API?"
    assert git_pool.remote_head("agent/PROJ-1-work") is None


@pytest.mark.parametrize(
    ("last_line", "exit_code"),
    [("not json", 0), ("", 0), ('{"status": "finished"}', 0), ('{"summary": "no status"}', 1)],
)
def test_bad_result_line_is_unknown(scenario: Scenario, git_pool: GitPool, last_line: str, exit_code: int) -> None:
    run = scenario.run(worker=worker_does(result=last_line, exit_code=exit_code))
    assert run.status == "unknown"
    assert json.loads(run.row["result_json"]) == {"harness": "the worker's last line was not a valid result"}


def test_result_text_is_bounded(scenario: Scenario, git_pool: GitPool) -> None:
    result = json.dumps({"status": "failed", "summary": "x" * 10000, "extra": "ignored"})
    run = scenario.run(worker=worker_does(result=result))
    stored = json.loads(run.row["result_json"])
    assert run.status == "failed"
    assert len(stored["summary"]) == 2000
    assert "extra" not in stored


def test_timeout(scenario: Scenario, git_pool: GitPool, treehouse_state: Path) -> None:
    run = scenario.run(runner=InlineRunner(timeout_agent=True))
    assert run.status == "timeout"
    assert json.loads(run.row["result_json"]) == {"harness": "the worker timed out after 45 minutes"}
    assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_existing_branch_on_origin_is_continued(scenario: Scenario, git_pool: GitPool) -> None:
    seed = git_pool.slots[1]
    git("checkout", "--quiet", "-b", "agent/PROJ-1-work", "origin/main", cwd=seed)
    git("commit", "--quiet", "--allow-empty", "-m", "earlier work", cwd=seed)
    git("push", "--quiet", "origin", "agent/PROJ-1-work", cwd=seed)
    git("checkout", "--quiet", "--detach", cwd=seed)

    scenario.run(worker=worker_does(["git", "log", "-1", "--format=%s"]))
    [w] = agent_runs(scenario.agent_log)
    commands = w["commands"]
    assert isinstance(commands, list)
    assert commands[0]["stdout"] == "earlier work\n"


def test_worker_refuses_to_start_on_a_branch_that_defines_its_agent(
    scenario: Scenario,
    git_pool: GitPool,
    treehouse_state: Path,
    tmp_path: Path,
) -> None:
    # Anyone who can push to the repository could commit this (TRUST_MODEL T7).
    clone = tmp_path / "pusher"
    git("clone", "--quiet", str(git_pool.origin), str(clone), cwd=tmp_path)
    agent = clone / ".opencode" / "agent" / "canopy-worker.md"
    agent.parent.mkdir(parents=True)
    agent.write_text('---\npermission:\n  bash:\n    "*": allow\n    "canopy *": allow\n---\n')
    git("add", ".", cwd=clone)
    git("commit", "--quiet", "-m", "loosen the worker", cwd=clone)
    git("push", "--quiet", "origin", "main", cwd=clone)

    run = scenario.run()
    assert run.status == "crashed"
    assert "defines one of canopy's agents" in json.loads(run.row["result_json"])["harness"]
    assert not scenario.agent_log.exists()
    assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_git_failure_is_crashed_and_returns_the_slot(
    scenario: Scenario,
    git_pool: GitPool,
    treehouse_state: Path,
) -> None:
    for slot in git_pool.slots:
        git("remote", "set-url", "origin", str(git_pool.origin.parent / "gone.git"), cwd=slot)
    run = scenario.run()
    assert run.status == "crashed"
    assert json.loads(run.row["result_json"])["harness"].startswith("repo: git fetch exited 128")
    assert not scenario.agent_log.exists()  # the worker never ran
    assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_a_run_is_claimed_once(scenario: Scenario, git_pool: GitPool, capsys: pytest.CaptureFixture[str]) -> None:
    conn = scenario.conn
    run = scenario.run()
    # `canopy _run` is canopy's own command, not the operator's: it is run as the detached process runs it.
    assert main(["_run", str(run.id)]) == 1
    assert "is not waiting to start" in capsys.readouterr().err
    assert main(["_run", "99"]) == 1
    assert "no run 99" in capsys.readouterr().err

    # A running run that another process claimed is refused too: the overseer cannot start a second worker in a slot.
    working = scenario.starts(dispatches("PROJ-2"))
    assert main(["_run", str(working.id)]) == 1
    assert "is not waiting to start" in capsys.readouterr().err
    still = present(db.get_run(conn, working.id))
    assert (still["status"], still["pid"]) == ("running", working.row["pid"])
    assert len(agent_runs(scenario.agent_log)) == 1


def test_sigterm_returns_the_slot(scenario: Scenario, git_pool: GitPool, treehouse_state: Path) -> None:
    # Signal this process once the worker has started; `_run` turns SIGTERM into cleanup.
    timer = threading.Timer(1.5, os.kill, (os.getpid(), signal.SIGTERM))
    timer.start()
    try:
        run = scenario.run(worker=worker_does(sleep=30))
    finally:
        timer.cancel()
    assert run.status == "crashed"
    assert json.loads(run.row["result_json"]) == {"harness": "stopped by signal SIGTERM"}
    assert all(s["status"] == "available" for s in pool(treehouse_state))
    assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL


def test_only_true_says_a_check_was_flaky_and_nothing_else_costs_the_result() -> None:
    assert present(worker.parse_result('{"status": "done", "flaky": true}')).flaky
    for said in ('"yes"', '"true"', "1", "null", "false"):
        assert not present(worker.parse_result(f'{{"status": "done", "flaky": {said}}}')).flaky
    assert not present(worker.parse_result('{"status": "done"}')).flaky


def test_a_flaky_cause_outside_the_vocabulary_is_no_estimate_and_costs_nothing() -> None:
    for cause in FlakyCause:
        assert present(
            worker.parse_result(f'{{"status": "done", "flaky": true, "flaky_cause": "{cause}"}}'),
        ).flaky_cause
    for said in ('"tests"', '"network"', "1", "null", "[]"):
        parsed = present(worker.parse_result(f'{{"status": "done", "flaky": true, "flaky_cause": {said}}}'))
        assert parsed.flaky
        assert parsed.flaky_cause is None
    assert present(worker.parse_result('{"status": "done", "flaky": true}')).flaky_cause is None


def test_a_flaky_detail_is_one_line_and_cut_and_anything_but_text_is_none() -> None:
    def detail(said: str) -> str | None:
        return present(worker.parse_result(f'{{"status": "done", "flaky": true, "flaky_detail": {said}}}')).flaky_detail

    assert detail('"registry.npmjs.org\\nreturned 503"') == "registry.npmjs.org returned 503"
    long = present(detail(json.dumps("x" * 400)))
    assert len(long) == worker.MAX_FLAKY_DETAIL
    assert long.endswith("...")
    for said in ('"  "', "1", "null", "[]"):
        assert detail(said) is None


def test_parse_result_takes_the_last_json_object_line() -> None:
    parsed = present(worker.parse_result('chatter\n{"status": "done"}\n\n  \n'))
    assert parsed.status == "done"
    # A plugin's notice after the result is passed over (DESIGN §13).
    parsed = present(worker.parse_result('{"status": "done"}\n[policy-plugin] session audited\n'))
    assert parsed.status == "done"
    # An invalid last object is no result, even with a valid one before it.
    assert worker.parse_result('{"status": "done"}\n{"status": "finished"}\nchatter\n') is None
    assert worker.parse_result("chatter only\n") is None


@contextmanager
def report_events(canopy_env: CanopyEnv) -> Iterator[None]:
    """Have the worker's template ask for OpenCode's JSON events, as the default does, with session `ses_w1`."""
    with_events(canopy_env, "canopy-worker")
    with scripted("WORKER", {}, {"session": "ses_w1"}):
        yield


def test_a_worker_records_the_session_and_cost_it_reported(
    scenario: Scenario,
    git_pool: GitPool,
    opencode_state: Path,
) -> None:
    sessions = {"ses_w1": [["anthropic", "claude-x", 0.25]]}
    opencode_state.write_text(json.dumps({"sessions": sessions, "version": "1.19.3"}))
    with report_events(scenario.env):
        run = scenario.run(worker=pushes())

    # The result line is read from the events' text, as it is from stdout without them.
    assert run.status == "done"
    assert json.loads(run.row["result_json"])["summary"] == "did it"
    assert unit_of(scenario.conn, "PROJ-1").pr_url == "https://example.test/pr/1"
    # Two model calls, summed.
    row = run.row
    assert row["session_id"] == "ses_w1"
    assert row["cost_usd"] == 0.25
    tokens = ("tokens_input", "tokens_output", "tokens_reasoning", "tokens_cache_read", "tokens_cache_write")
    assert tuple(row[c] for c in tokens) == (2000, 400, 60, 8000, 1000)
    assert row["tokens_peak_context"] == 1000 + 4000 + 500  # one call's input, cache read, and cache write
    first = ("tokens_first_call", "tokens_first_cache_write", "tokens_first_cache_read")
    assert tuple(row[c] for c in first) == (5500, 500, 4000)
    assert (scenario.env.state_dir / definitions.RUNTIME_DIR / row["definitions_digest"]).is_dir()  # the one it loaded
    # Each command the fake ran is a `bash` call that returned its stdout.
    assert tools_of(scenario.conn, "runs", run.id) == tools_printed(scenario.agent_log, "canopy-worker") != []
    # Which models served it, read from its session as it ended (DESIGN §13).
    assert [(m.model, m.replies) for m in run_models.of_run(scenario.conn, "runs", run.id)] == [
        ("anthropic/claude-x", 1),
    ]
    # And the OpenCode that ran it.
    assert run_models.reads_of(scenario.conn, "runs", [run.id])[run.id].runtime_version == "1.19.3"

    out = scenario.operator("status").out
    assert re.search(r"\nRecent runs \(1\):\n  PROJ-1  implement  done  \d+s ago  https://example.test/pr/1\n", out)
    # And the persona it ran in, by name and the start of its digest (DESIGN §31), and the model that served it.
    persona = f"persona canopy {row['persona_digest'][:12]}"
    said = f"session ses_w1  $0.25, 3.5k tokens, 5.5k peak context  {persona}  served anthropic/claude-x"
    assert f"\n    did it\n    {said}  log {row['log_path']}\n" in out


def test_status_names_each_model_that_served_a_run_with_its_cost(
    scenario: Scenario,
    git_pool: GitPool,
    opencode_state: Path,
) -> None:
    """A run more than one model served names each in `canopy status`, the most costly first (DESIGN §13)."""
    calls = [["openai", "gpt-y", 0.1], ["anthropic", "claude-x", 0.25], ["anthropic", "claude-x", 0.15]]
    opencode_state.write_text(json.dumps({"sessions": {"ses_w1": calls}}))
    with report_events(scenario.env):
        run = scenario.run(worker=pushes())

    out = scenario.operator("status").out
    assert f"  served anthropic/claude-x $0.40, openai/gpt-y $0.10  log {run.row['log_path']}\n" in out


def test_a_running_worker_shows_its_session_spend_and_latest_tool_call(scenario: Scenario, git_pool: GitPool) -> None:
    """What the worker reports is on its row as it prints it, so its second command sees what its first did."""
    root = scenario.env.root
    status = ["sh", "-c", f"cd {root} && canopy status"]
    with report_events(scenario.env):
        run = scenario.run(worker=worker_does(["true"], status))

    [agent] = agent_runs(scenario.agent_log)
    commands = agent["commands"]
    assert isinstance(commands, list)
    _, shown = commands
    # One model call so far, and `true` was its last tool call: `canopy status` itself has not ended yet.
    line = r"\n    session ses_w1  \$0\.12, 1\.7k tokens, 5\.5k peak context  last bash: true \d+s ago\n"
    assert re.search(line, shown["stdout"])

    # Once it ends, its row has its whole report, and its log what it printed in the same shape as ever.
    assert (run.status, run.row["session_id"], run.row["cost_usd"]) == ("done", "ses_w1", 0.25)
    assert (run.row["activity_tool"], run.row["activity"]) == ("bash", f"sh -c cd {root} && canopy status")
    out = run.printed.out
    assert re.search(r"--- worker stdout ---\n(\{.*\}\n)+\n--- worker stderr ---\n\n--- worker exit 0 ---\n", out)


def test_a_journal_that_refuses_a_progress_write_does_not_stop_the_worker(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    refused = sqlite3.OperationalError("database is locked")
    with (
        report_events(scenario.env),
        mock.patch.object(db, "set_run_progress", autospec=True, side_effect=refused) as progress,
    ):
        run = scenario.run(worker=pushes())
    assert progress.called
    # Recorded once it ended, as ever.
    assert (run.status, run.row["session_id"], run.row["cost_usd"]) == ("done", "ses_w1", 0.25)


def test_a_timed_out_worker_records_what_it_reported_before_the_kill(scenario: Scenario, git_pool: GitPool) -> None:
    tokens = {"input": 1, "output": 2, "reasoning": 0, "cache": {"read": 3, "write": 4}}
    events = [
        {"type": "step_finish", "sessionID": "ses_slow", "part": {"cost": 0.5, "tokens": tokens}},
        {"type": "text", "sessionID": "ses_slow", "part": {"type": "text", "text": "still going"}},
    ]
    stdout = "".join(json.dumps(e) + "\n" for e in events)
    with report_events(scenario.env):
        run = scenario.run(runner=InlineRunner(timeout_agent=True, timeout_stdout=stdout))
    assert run.status == "timeout"
    assert (run.row["session_id"], run.row["cost_usd"], run.row["tokens_cache_write"]) == ("ses_slow", 0.5, 4)


def test_a_worker_without_events_reports_no_session(scenario: Scenario, git_pool: GitPool) -> None:
    summary = "\x1b[2Jcleared the screen\nand  went on   " + "x" * 300
    result = json.dumps({"status": "failed", "summary": summary, "pr": "https://x.test/\x1b"})
    run = scenario.run(worker=worker_does(result=result))
    assert (run.status, run.row["session_id"], run.row["cost_usd"]) == ("failed", None, None)

    out = scenario.operator("status").out
    # Agent-written text reaches the terminal on one line, without control characters, and cut; a PR that is not a
    # plain URL is not printed at all.
    assert re.search(r"\n  PROJ-1  implement  failed  \d+s ago\n", out)
    assert "\x1b" not in out
    [said] = [line for line in out.splitlines() if line.startswith("    [2J")]
    assert said == "    [2Jcleared the screen and went on " + "x" * 123 + "..."
    assert len(said) == 4 + 160
    persona = f"persona canopy {run.row['persona_digest'][:12]}"
    assert f"\n    no session reported  {persona}  log {run.row['log_path']}\n" in out


def test_status_lists_recent_runs_newest_first(
    canopy_env: CanopyEnv,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["status"]) == 0
    assert "\nRecent runs (0):\n  none\n" in capsys.readouterr().out
    tick_id = db.start_tick(conn, dry_run=False)
    db.touch_ticket(conn, "PROJ-1", str(canopy_env.root))
    for n in range(12):
        run_id = db.insert_run(
            conn,
            tick_id=tick_id,
            key="PROJ-1",
            kind="fix-ci",
            branch="b",
            slots=[],
            runs_dir=Path(),
        )
        db.finish_run(conn, "runs", run_id, RunStatus.DONE, json.dumps({"summary": f"run {n + 1}"}))
    running = db.insert_run(conn, tick_id=tick_id, key="PROJ-1", kind="resume", branch="b", slots=[], runs_dir=Path())

    assert main(["status"]) == 0
    out = capsys.readouterr().out
    recent = out[out.index("Recent runs") :]
    assert re.match(r"Recent runs \(10\):\n  PROJ-1  fix-ci  done  \d+s ago\n    run 12\n", recent)
    assert "run 3\n" in recent
    assert "run 2\n" not in recent
    assert db.get_run(conn, running) is not None
    assert "resume" not in recent
