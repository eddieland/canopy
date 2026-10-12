"""Blockers and stacking: `canopy dispatch --base` and a stacked run's branch and PR base (DESIGN §10)."""

import json
import sqlite3
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import db
from tests.canopy.helpers import InlineRunner, in_tick, journal, pool, slot_of, wait_for_run, worker_does
from tests.conftest import CanopyEnv, GitPool, git

LABEL = "agent-ready-tester"
FIRST = "agent/PROJ-1-first"
# Pushes whatever branch `_run` checked out to the same name on origin.
PUSH = ["git", "push", "--quiet", "origin", "HEAD"]


@pytest.fixture
def conn(canopy_env: CanopyEnv) -> sqlite3.Connection:
    return journal(canopy_env)


def decisions(conn: sqlite3.Connection, tick_id: int) -> list[tuple[str, str]]:
    return [(str(d["action"]), str(d["rationale"])) for d in db.decisions_for_tick(conn, tick_id)]


def commit(message: str) -> list[str]:
    return ["git", "commit", "--quiet", "--allow-empty", "-m", message]


def dispatch_and_run(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, key: str, *args: str
) -> tuple[sqlite3.Row, list[tuple[str, str]]]:
    """Dispatch in a fresh tick, then do the run in-process. Returns the closed run and the tick's decisions."""
    runner = InlineRunner()
    tick_id = in_tick(conn, monkeypatch)
    assert main(["dispatch", key, "--repo", "repo", *args], runner=runner) == 0, decisions(conn, tick_id)
    db.finish_tick(conn, tick_id, "ok", "test")
    run_id = int(conn.execute("SELECT max(id) FROM runs").fetchone()[0])
    assert main(["_run", str(run_id)], runner=runner) == 0
    run = db.get_run(conn, run_id)
    assert run is not None
    return run, decisions(conn, tick_id)


def prompt_of(env: CanopyEnv, run_id: int) -> str:
    """The run's rendered prompt with its line breaks read as spaces, as the worker reads it."""
    return " ".join((env.state_dir / "runs" / f"{run_id}.prompt").read_text().split())


def subjects(git_pool: GitPool, branch: str) -> list[str]:
    return git("log", "--format=%s", branch, cwd=git_pool.origin).splitlines()


@pytest.fixture
def blocker(git_pool: GitPool, agent_log: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    """PROJ-1 implemented and pushed as `agent/PROJ-1-first`: the branch of the blocker's open PR."""
    worker_does(monkeypatch, commit("PROJ-1: the blocker"), PUSH)
    run, _ = dispatch_and_run(conn, monkeypatch, "PROJ-1", "--label", LABEL, "--kind", "implement", "--slug", "first")
    assert run["status"] == "done"


def test_implement_stacked_on_a_blocker_starts_from_its_branch_and_targets_it(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    blocker: None,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_does(monkeypatch, commit("PROJ-2: stacked"), PUSH)
    run, made = dispatch_and_run(
        conn, monkeypatch, "PROJ-2", "--label", LABEL, "--kind", "implement", "--slug", "second", "--base", FIRST
    )

    slot = slot_of(conn, int(run["id"]))
    assert (run["status"], run["branch"], slot["base_branch"]) == ("done", "agent/PROJ-2-second", FIRST)
    assert made == [
        ("dispatch:implement", f"run 2: agent/PROJ-2-second on {FIRST} in repo at {slot['slot_path']}; label {LABEL}")
    ]
    assert subjects(git_pool, "agent/PROJ-2-second") == ["PROJ-2: stacked", "PROJ-1: the blocker", "initial"]
    assert subjects(git_pool, FIRST) == ["PROJ-1: the blocker", "initial"]  # the base is untouched
    prompt = prompt_of(canopy_env, 2)
    assert f": branch `agent/PROJ-2-second` from `{FIRST}`; PR: " in prompt
    assert f"This ticket is stacked: `{FIRST}` is the branch of another ticket's open PR" in prompt
    assert all(s["status"] == "available" for s in pool(treehouse_state))

    # The unstacked blocker's prompt said so.
    assert "This ticket is not stacked on another ticket's branch." in prompt_of(canopy_env, 1)
    assert ": branch `agent/PROJ-1-first` from `main`; PR: " in prompt_of(canopy_env, 1)


def test_later_runs_on_a_stacked_ticket_take_the_base_they_are_given(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    blocker: None,
    agent_log: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_does(monkeypatch, commit("PROJ-2: stacked"), PUSH)
    dispatch_and_run(
        conn, monkeypatch, "PROJ-2", "--label", LABEL, "--kind", "implement", "--slug", "second", "--base", FIRST
    )

    # While the blocker's PR is open the overseer passes the base again; the run continues the pushed branch.
    worker_does(monkeypatch, commit("PROJ-2: review fix"), PUSH)
    resume, _ = dispatch_and_run(conn, monkeypatch, "PROJ-2", "--label", LABEL, "--kind", "resume", "--base", FIRST)
    assert (resume["status"], slot_of(conn, int(resume["id"]))["base_branch"]) == ("done", FIRST)
    assert f": branch `agent/PROJ-2-second` from `{FIRST}`; PR: " in prompt_of(canopy_env, int(resume["id"]))

    # Once it merged, the overseer omits it: the run's base is the repository's, and the worker retargets the PR.
    worker_does(monkeypatch, PUSH)
    retarget, _ = dispatch_and_run(
        conn, monkeypatch, "PROJ-2", "--label", LABEL, "--kind", "resume", "--context", "blocker merged"
    )
    assert (retarget["status"], slot_of(conn, int(retarget["id"]))["base_branch"]) == ("done", "main")
    text = prompt_of(canopy_env, int(retarget["id"]))
    assert "This ticket is not stacked on another ticket's branch." in text
    assert ": branch `agent/PROJ-2-second` from `main`; PR: " in text
    assert "change this ticket's PR to target its repository's base branch listed above" in text
    assert subjects(git_pool, "agent/PROJ-2-second")[:2] == ["PROJ-2: review fix", "PROJ-2: stacked"]

    # The overseer sees which base each ticket's latest run started from.
    monkeypatch.delenv("CANOPY_TICK_ID", raising=False)
    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")
    assert main(["tick"]) == 0
    prompt = json.loads(agent_log.read_text().splitlines()[-1])["argv"][-1]
    state = json.loads(prompt.split("```json\n", 1)[1].split("\n```", 1)[0])
    bases = {t["key"]: t["last_run"]["repos"] for t in state["tickets"]}
    assert bases == {"PROJ-1": [{"repo": "repo", "base": "main"}], "PROJ-2": [{"repo": "repo", "base": "main"}]}


def test_a_base_gone_from_origin_is_crashed_and_returns_the_slot(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The blocker's PR merged and its branch was deleted between the overseer's look and the run.
    run, _ = dispatch_and_run(conn, monkeypatch, "PROJ-2", "--label", LABEL, "--kind", "implement", "--base", FIRST)
    assert run["status"] == "crashed"
    note = json.loads(run["result_json"])["harness"]
    assert note == f"repo: the base branch {FIRST} is not on origin; if it was stacked on, its PR may have merged"
    assert not agent_log.exists()  # the worker never ran
    assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_a_continued_branch_whose_base_is_gone_is_crashed(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    blocker: None,
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_does(monkeypatch, commit("PROJ-2: stacked"), PUSH)
    dispatch_and_run(
        conn, monkeypatch, "PROJ-2", "--label", LABEL, "--kind", "implement", "--slug", "second", "--base", FIRST
    )
    workers = len(agent_log.read_text().splitlines())

    # The blocker's branch is deleted after PROJ-2's branch exists; a resume still naming it must not start.
    git("branch", "--quiet", "-D", FIRST, cwd=git_pool.origin)
    run, _ = dispatch_and_run(conn, monkeypatch, "PROJ-2", "--label", LABEL, "--kind", "resume", "--base", FIRST)
    assert run["status"] == "crashed"
    assert json.loads(run["result_json"])["harness"].startswith(f"repo: the base branch {FIRST} is not on origin")
    assert len(agent_log.read_text().splitlines()) == workers  # the worker never ran
    assert all(s["status"] == "available" for s in pool(treehouse_state))


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        (["--base", "main"], "--base must be another ticket's branch, agent/<KEY>-<slug>"),
        (["--base", "agent/"], "--base must be another ticket's branch, agent/<KEY>-<slug>"),
        (["--base", "agent/PROJ-1/x"], "--base must be another ticket's branch, agent/<KEY>-<slug>"),
        (["--base", "agent/../main"], "--base must be another ticket's branch, agent/<KEY>-<slug>"),
        (["--base", "agent/-x"], "--base must be another ticket's branch, agent/<KEY>-<slug>"),
        (["--base", "agent/PROJ-1-a b"], "--base must be another ticket's branch, agent/<KEY>-<slug>"),
        (["--base", "agent/" + "x" * 201], "--base must be another ticket's branch, agent/<KEY>-<slug>"),
        (["--slug", "own", "--base", "agent/PROJ-2-own"], "agent/PROJ-2-own cannot be stacked on itself"),
    ],
)
def test_bad_base_is_refused_before_leasing(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
    args: list[str],
    reason: str,
) -> None:
    tick_id = in_tick(conn, monkeypatch)
    assert (
        main(
            ["dispatch", "PROJ-2", "--repo", "repo", "--label", LABEL, "--kind", "implement", *args],
            runner=InlineRunner(),
        )
        == 1
    )
    assert decisions(conn, tick_id) == [("refused:bad_base", reason)]
    assert not treehouse_state.exists()


def test_a_continued_branch_cannot_be_its_own_base(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    db.touch_ticket(conn, "PROJ-2", str(canopy_env.root))
    conn.execute("UPDATE tickets SET branch = 'agent/PROJ-2-own' WHERE key = 'PROJ-2'")
    conn.execute("INSERT INTO ticket_units (ticket_key, repo, branch) VALUES ('PROJ-2', 'repo', 'agent/PROJ-2-own')")
    tick_id = in_tick(conn, monkeypatch)
    assert (
        main(
            [
                "dispatch",
                "PROJ-2",
                "--repo",
                "repo",
                "--label",
                LABEL,
                "--kind",
                "resume",
                "--base",
                "agent/PROJ-2-own",
            ],
            runner=InlineRunner(),
        )
        == 1
    )
    assert decisions(conn, tick_id) == [("refused:bad_base", "agent/PROJ-2-own cannot be stacked on itself")]


def test_dry_run_names_the_base(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    tick_id = in_tick(conn, monkeypatch, dry_run=True)
    args = [
        "dispatch",
        "PROJ-2",
        "--repo",
        "repo",
        "--label",
        LABEL,
        "--kind",
        "implement",
        "--slug",
        "second",
        "--base",
        FIRST,
    ]
    assert main(args, runner=InlineRunner()) == 0
    rationale = f"dry run: not dispatched; would work on agent/PROJ-2-second on {FIRST} in repo; label {LABEL}"
    assert decisions(conn, tick_id) == [("dispatch:implement", rationale)]
    assert not treehouse_state.exists()


def test_two_linked_tickets_are_worked_in_order(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M4 acceptance, the harness's half, against the fakes. The overseer's reading of blockers and PR state is prompt
    behavior: here a scripted overseer waits on the blocked ticket, then stacks it once the blocker's PR exists."""
    worker_does(monkeypatch, commit("the change"), PUSH)
    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")
    monkeypatch.setenv(
        "FAKE_OVERSEER_COMMANDS",
        json.dumps(
            [
                [
                    "canopy",
                    "dispatch",
                    "PROJ-1",
                    "--repo",
                    "repo",
                    "--label",
                    LABEL,
                    "--kind",
                    "implement",
                    "--slug",
                    "first",
                ],
                ["canopy", "decide", "PROJ-2", "wait", "--rationale", "blocked_by: PROJ-1"],
                ["canopy", "ticket", "set", "PROJ-2", "--repo", "repo", "--phase", "blocked"],
            ]
        ),
    )
    assert main(["tick"]) == 0
    assert wait_for_run(conn, 1)["status"] == "done"

    monkeypatch.setenv(
        "FAKE_OVERSEER_COMMANDS",
        json.dumps(
            [
                ["canopy", "decide", "PROJ-1", "wait", "--rationale", "ci_running"],
                [
                    "canopy",
                    "dispatch",
                    "PROJ-2",
                    "--repo",
                    "repo",
                    "--label",
                    LABEL,
                    "--kind",
                    "implement",
                    "--slug",
                    "second",
                    "--base",
                    FIRST,
                ],
            ]
        ),
    )
    assert main(["tick"]) == 0
    second = wait_for_run(conn, 2)
    assert (second["status"], slot_of(conn, 2)["base_branch"]) == ("done", FIRST)

    ticks = [int(r["id"]) for r in conn.execute("SELECT id FROM ticks ORDER BY id")]
    assert [[a for a, _ in decisions(conn, t)] for t in ticks] == [
        ["dispatch:implement", "wait"],
        ["wait", "dispatch:implement"],
    ]
    assert git("merge-base", "--is-ancestor", FIRST, "agent/PROJ-2-second", cwd=git_pool.origin) == ""
    assert f": branch `agent/PROJ-2-second` from `{FIRST}`; PR: " in prompt_of(canopy_env, 2)
    assert all(s["status"] == "available" for s in pool(treehouse_state))


@pytest.mark.usefixtures("treehouse_state")
def test_the_state_block_carries_the_stacking_policy(
    canopy_env: CanopyEnv, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def stacking() -> str:
        monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")
        assert main(["tick"]) == 0
        prompt = json.loads(agent_log.read_text().splitlines()[-1])["argv"][-1]
        return json.loads(prompt.split("```json\n", 1)[1].split("\n```", 1)[0])["policy"]["stacking"]

    assert stacking() == "auto"
    canopy_env.write_shared(canopy_env.shared_file.read_text() + '[policy]\nstacking = "never"\n')
    assert stacking() == "never"
