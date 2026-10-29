"""Blockers and stacking: `canopy dispatch --base` and a stacked run's branch and PR base (DESIGN §10)."""

import json
from pathlib import Path

import pytest

from canopy.core import db
from canopy.core.vocab import Phase, ResumeReason, RunKind
from tests.canopy.helpers import (
    KEY,
    LABEL,
    agent_runs,
    decisions,
    pool,
    slot_of,
    waits,
    worker_does,
)
from tests.canopy.scenario_helpers import Ran, Scenario, dispatches, pushes, sets_phase
from tests.conftest import GitPool, git

FIRST = "agent/PROJ-1-first"
SECOND = "agent/PROJ-2-second"


def blocker(scenario: Scenario) -> Ran:
    """PROJ-1 implemented and pushed as `agent/PROJ-1-first`: the branch of the blocker's open PR.

    Returns:
        Its run.
    """
    run = scenario.run(dispatches(slug="first"), worker=pushes(FIRST, "PROJ-1: the blocker"))
    assert run.status == "done"
    return run


def stacked(scenario: Scenario) -> Ran:
    """PROJ-2 implemented on `agent/PROJ-2-second`, stacked on the blocker's branch.

    Returns:
        Its run.
    """
    return scenario.run(dispatches("PROJ-2", slug="second", base=FIRST), worker=pushes(SECOND, "PROJ-2: stacked"))


def read(run: Ran) -> str:
    """The run's rendered prompt with its line breaks read as spaces, as the worker reads it."""
    return " ".join(run.prompt.split())


def subjects(git_pool: GitPool, branch: str) -> list[str]:
    return git("log", "--format=%s", branch, cwd=git_pool.origin).splitlines()


def test_implement_stacked_on_a_blocker_starts_from_its_branch_and_targets_it(
    scenario: Scenario,
    git_pool: GitPool,
    treehouse_state: Path,
) -> None:
    first = blocker(scenario)
    run = stacked(scenario)

    slot = slot_of(scenario.conn, run.id)
    assert (run.status, run.branch, slot.base_branch) == ("done", "agent/PROJ-2-second", FIRST)
    assert decisions(scenario.conn, int(run.row["tick_id"])) == [
        (
            "dispatch:implement",
            f"run 2: agent/PROJ-2-second on {FIRST} in repo at {slot.slot_path}; label {LABEL}",
        ),
    ]
    assert subjects(git_pool, "agent/PROJ-2-second") == ["PROJ-2: stacked", "PROJ-1: the blocker", "initial"]
    assert subjects(git_pool, FIRST) == ["PROJ-1: the blocker", "initial"]  # the base is untouched
    prompt = read(run)
    assert f": branch `agent/PROJ-2-second` from `{FIRST}`; PR: " in prompt
    assert f"This ticket is stacked: `{FIRST}` is the branch of another ticket's open PR" in prompt
    assert all(s["status"] == "available" for s in pool(treehouse_state))

    # The unstacked blocker's prompt said so.
    assert "This ticket is not stacked on another ticket's branch." in read(first)
    assert ": branch `agent/PROJ-1-first` from `main`; PR: " in read(first)


def test_later_runs_on_a_stacked_ticket_take_the_base_they_are_given(scenario: Scenario, git_pool: GitPool) -> None:
    blocker(scenario)
    stacked(scenario)

    # While the blocker's PR is open the overseer passes the base again; the run continues the pushed branch.
    review = dispatches("PROJ-2", RunKind.RESUME, reasons=[ResumeReason.REVIEW], base=FIRST)
    resume = scenario.run(review, worker=pushes(SECOND, "PROJ-2: review fix"))
    assert (resume.status, slot_of(scenario.conn, resume.id).base_branch) == ("done", FIRST)
    assert f": branch `agent/PROJ-2-second` from `{FIRST}`; PR: " in read(resume)
    # The overseer sees the base a stacked ticket's latest run started from; an unstacked one's shows none.
    scenario.tick(*waits("PROJ-1", "PROJ-2", rationale="PR open"))
    assert "repos" not in scenario.ticket_state("PROJ-1")["last_run"]
    assert scenario.ticket_state("PROJ-2")["last_run"]["repos"] == [{"repo": "repo", "base": FIRST}]

    # Once it merged, the overseer omits it: the run's base is the repository's, and the worker retargets the PR.
    merged = dispatches("PROJ-2", RunKind.RESUME, reasons=[ResumeReason.RETARGET], context="blocker merged")
    retarget = scenario.run(
        merged,
        worker=worker_does(["git", "push", "--quiet", "origin", f"HEAD:refs/heads/{SECOND}"]),
    )
    assert (retarget.status, slot_of(scenario.conn, retarget.id).base_branch) == ("done", "main")
    text = read(retarget)
    assert "This ticket is not stacked on another ticket's branch." in text
    assert ": branch `agent/PROJ-2-second` from `main`; PR: " in text
    assert "- `retarget`: the PR this ticket was stacked on has merged" in text
    assert "change this ticket's PR to target its repository's base branch listed above" in text
    assert subjects(git_pool, "agent/PROJ-2-second")[:2] == ["PROJ-2: review fix", "PROJ-2: stacked"]

    # Retargeted, it is stacked no more, and its latest run shows no base.
    scenario.tick(*waits("PROJ-1", "PROJ-2", rationale="PR open"))
    assert ["repos" in t["last_run"] for t in scenario.state()["tickets"]] == [False, False]


def test_a_base_gone_from_origin_is_crashed_and_returns_the_slot(
    scenario: Scenario,
    git_pool: GitPool,
    treehouse_state: Path,
) -> None:
    # The blocker's PR merged and its branch was deleted between the overseer's look and the run.
    run = scenario.run(dispatches("PROJ-2", base=FIRST))
    assert run.status == "crashed"
    note = json.loads(run.row["result_json"])["harness"]
    assert note == f"repo: the base branch {FIRST} is not on origin; if it was stacked on, its PR may have merged"
    assert not scenario.agent_log.exists()  # the worker never ran
    assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_a_continued_branch_whose_base_is_gone_is_crashed(
    scenario: Scenario,
    git_pool: GitPool,
    treehouse_state: Path,
) -> None:
    blocker(scenario)
    stacked(scenario)
    workers = len(agent_runs(scenario.agent_log))

    # The blocker's branch is deleted after PROJ-2's branch exists; a resume still naming it must not start.
    git("branch", "--quiet", "-D", FIRST, cwd=git_pool.origin)
    run = scenario.run(
        dispatches("PROJ-2", RunKind.RESUME, reasons=[ResumeReason.CI], base=FIRST),
        worker=pushes(SECOND),
    )
    assert run.status == "crashed"
    assert json.loads(run.row["result_json"])["harness"].startswith(f"repo: the base branch {FIRST} is not on origin")
    assert len(agent_runs(scenario.agent_log)) == workers  # the worker never ran
    assert all(s["status"] == "available" for s in pool(treehouse_state))


BAD_BASE = "base (--base) must be another ticket's branch, agent/<KEY>-<slug>"


@pytest.mark.parametrize(
    ("slug", "base", "reason"),
    [
        (None, "main", BAD_BASE),
        (None, "agent/", BAD_BASE),
        (None, "agent/PROJ-1/x", BAD_BASE),
        (None, "agent/../main", BAD_BASE),
        (None, "agent/-x", BAD_BASE),
        (None, "agent/PROJ-1-a b", BAD_BASE),
        (None, "agent/" + "x" * 201, BAD_BASE),
        ("own", "agent/PROJ-2-own", "agent/PROJ-2-own cannot be stacked on itself"),
    ],
)
def test_bad_base_is_refused_before_leasing(
    scenario: Scenario,
    treehouse_state: Path,
    slug: str | None,
    base: str,
    reason: str,
) -> None:
    assert scenario.refuses(dispatches("PROJ-2", slug=slug, base=base)) == [("refused:bad_base", reason)]
    assert not treehouse_state.exists()


def test_a_continued_branch_cannot_be_its_own_base(scenario: Scenario) -> None:
    conn = scenario.conn
    db.touch_ticket(conn, "PROJ-2", str(scenario.env.root))
    conn.execute("UPDATE tickets SET branch = 'agent/PROJ-2-own' WHERE key = 'PROJ-2'")
    conn.execute("INSERT INTO ticket_units (ticket_key, repo, branch) VALUES ('PROJ-2', 'repo', 'agent/PROJ-2-own')")
    own = dispatches("PROJ-2", RunKind.RESUME, reasons=[ResumeReason.CONFLICT], base="agent/PROJ-2-own")
    assert scenario.refuses(own) == [("refused:bad_base", "agent/PROJ-2-own cannot be stacked on itself")]


def test_dry_run_names_the_base(scenario: Scenario, treehouse_state: Path) -> None:
    ticked = scenario.tick(dispatches("PROJ-2", slug="second", base=FIRST), dry_run=True)
    rationale = f"dry run: not dispatched; would work on agent/PROJ-2-second on {FIRST} in repo; label {LABEL}"
    assert [(d.action, d.rationale) for d in ticked.decisions[1:]] == [("dispatch:implement", rationale)]
    # The tick reads the pool's status; the dry run leases nothing.
    calls: list[list[str]] = json.loads(treehouse_state.read_text())["calls"]
    assert [c for c in calls if c[0] != "status"] == []


def test_two_linked_tickets_are_worked_in_order(scenario: Scenario, git_pool: GitPool, treehouse_state: Path) -> None:
    """M4 acceptance, the harness's half, against the fakes.

    The overseer's reading of blockers and PR state is prompt behavior: here a scripted overseer waits on the blocked
    ticket, then stacks it once the blocker's PR exists.
    """
    # Both tickets' workers run this, so neither pushes: `_run`'s own push puts each branch on origin (DESIGN §8).
    commits = worker_does(["git", "commit", "--quiet", "--allow-empty", "-m", "the change"])
    first = scenario.tick(
        dispatches(slug="first"),
        *waits("PROJ-2", rationale="blocked_by: PROJ-1"),
        sets_phase("PROJ-2", Phase.BLOCKED, repo="repo"),
        worker=commits,
    )
    assert [r.status for r in first.runs] == ["done"]

    then = scenario.tick(
        *waits("PROJ-1", rationale="ci_running"),
        dispatches("PROJ-2", slug="second", base=FIRST),
        worker=commits,
    )
    [second] = then.runs
    assert (second.status, slot_of(scenario.conn, second.id).base_branch) == ("done", FIRST)

    ticks = [int(r["id"]) for r in scenario.conn.execute("SELECT id FROM ticks ORDER BY id")]
    assert [[a for a, _ in decisions(scenario.conn, t)] for t in ticks] == [
        # A dispatch's decision is recorded as the tick starts it, after the overseer's run (DESIGN §40).
        ["queried", "wait", "dispatch:implement"],
        ["queried", "wait", "dispatch:implement"],
    ]
    assert git("merge-base", "--is-ancestor", FIRST, "agent/PROJ-2-second", cwd=git_pool.origin) == ""
    assert f": branch `agent/PROJ-2-second` from `{FIRST}`; PR: " in read(second)
    assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_the_state_block_carries_the_stacking_policy(scenario: Scenario) -> None:
    def stacking() -> str:
        scenario.tick(*waits(KEY))
        return scenario.state()["policy"]["stacking"]

    assert stacking() == "auto"
    scenario.configures("workspace", policy={"stacking": "never"})
    assert stacking() == "never"
