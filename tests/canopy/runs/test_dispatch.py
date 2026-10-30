"""The `dispatch` tool outside a dry run: guards, lease, and spawning `_run` (DESIGN §8)."""

import json
import os
import sqlite3
import sys
from pathlib import Path
from unittest import mock

import pytest

from canopy.core import db
from canopy.core.context import Context
from canopy.core.vocab import ResumeReason, RunKind, RunStatus
from canopy.infra import procs
from canopy.runs import dispatch
from tests.canopy.helpers import (
    LABEL,
    Called,
    InlineRunner,
    decisions,
    in_tick,
    lifelock_left,
    overseer_calls,
    pool,
    present,
    slot_of,
    tick_starts,
    tracker_holds,
)
from tests.canopy.scenario_helpers import Scenario, dispatches, pushes
from tests.conftest import CanopyEnv, GitPool, pool_state


def test_dispatch_leases_records_and_spawns(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    tracker_holds(conn)
    with in_tick(conn) as tick_id:
        runner = InlineRunner()
        said = overseer_calls(dispatches(slug="add-login"), runner=runner)
        assert not said.error, said.text
        # Recorded, and started by the tick once its overseer's run ends (DESIGN §40).
        assert db.get_run(conn, 1) is None
        tick_starts(runner)

        run = present(db.get_run(conn, 1))
        assert (run["ticket_key"], run["kind"], run["status"]) == ("PROJ-1", "implement", "running")
        assert run["branch"] == "agent/PROJ-1-add-login"
        assert run["pid"] == os.getpid()
        assert run["log_path"] == str(canopy_env.state_dir / "runs" / "1.log")
        leased = slot_of(conn, 1)
        assert (leased.repo, leased.base_branch, leased.lease_holder) == ("repo", "main", "canopy:PROJ-1")
        [slot] = [s for s in pool(treehouse_state) if s["status"] == "leased"]
        assert (slot["path"], slot["lease_id"]) == (leased.slot_path, leased.lease_id)

        assert runner.spawned == [(sys.executable, "-m", "canopy", "_run", "1")]
        [(action, rationale)] = decisions(conn, tick_id)
        assert action == "dispatch:implement"
        assert rationale == f"run 1: agent/PROJ-1-add-login in repo at {leased.slot_path}; label agent-ready-tester"
        # The worker is told which labels authorize it, so it can check the ticket itself (D051).
        assert "`agent-ready-tester`" in (canopy_env.state_dir / "runs" / "1.prompt").read_text()
        ticket = conn.execute("SELECT * FROM tickets WHERE key = 'PROJ-1'").fetchone()
        assert ticket["branch"] == "agent/PROJ-1-add-login"

        prompt = canopy_env.state_dir / "runs" / "1.prompt"
        assert prompt.stat().st_mode & 0o777 == 0o600
        text = prompt.read_text()
        assert text.startswith("# canopy worker: implement")
        assert "{{" not in text
        assert f"ticket PROJ-1 in {leased.slot_path}." in text
        assert "This run works in one repository:\n- `repo` at `" + str(leased.slot_path) in text
        assert ": branch `agent/PROJ-1-add-login` from `main`; PR: not recorded; look up the PR for " in text
        assert '"prs":{"repo":"<url or null>"}' in text
        assert text.lower().count("add the label") == 1, "only the ticket's needs-human label, never the PR's"
        assert "Time limit: 45 minutes" in text


def test_worker_is_told_the_configured_needs_human_label(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures("workspace", tracker={"needs_human_label": "blocked-on-team"})
    text = scenario.run().prompt
    assert "Add the label `blocked-on-team` to the ticket" in text
    assert "needs-human" not in text


def test_worker_is_told_the_configured_comment_marks(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.configures(trust={"comment_prefix": "[bot]", "comment_suffix": "Posted by canopy for alice."})
    text = scenario.run().prompt
    assert "start it with `[bot]` and a space, and end it with `Posted by canopy for alice.`" in text
    assert "a comment that starts with `[bot]` and ends with `Posted by canopy for alice.` outside any quote" in text
    assert "CANOPY:" not in text


def test_worker_opens_prs_through_the_mcp_or_the_configured_skill(scenario: Scenario, git_pool: GitPool) -> None:
    assert "Never target another branch. Open each PR through the GitHub MCP." in scenario.run().prompt

    # The operator's own skill replaces the MCP, with no fallback to it.
    scenario.configures(runtime={"pr_skill": "acme-pr"})
    text = scenario.run(dispatches("PROJ-2")).prompt
    assert "Never target another branch. Open each PR by following the skill `acme-pr`, and in no other way" in text
    assert "Open each PR through the GitHub MCP" not in text


def test_an_override_that_ignores_the_pr_skill_is_refused(
    scenario: Scenario,
    git_pool: GitPool,
    treehouse_state: Path,
) -> None:
    overrides = scenario.env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text("Work {{KEY}} for {{LABELS}}; open a PR through the GitHub MCP\n")
    scenario.configures(runtime={"pr_skill": "acme-pr"})
    [(action, rationale)] = scenario.refuses(dispatches())
    assert action == "refused:bad_prompt"
    assert "missing required placeholder {{OPEN_PR}}" in rationale
    assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_detached_run_finishes_on_its_own(scenario: Scenario, git_pool: GitPool, treehouse_state: Path) -> None:
    [run] = scenario.tick(dispatches(), worker=pushes()).runs
    assert run.status == "done", Path(run.row["log_path"]).read_text()
    assert git_pool.remote_head("agent/PROJ-1-work") is not None
    assert all(s["status"] == "available" for s in pool(treehouse_state))
    log = Path(run.row["log_path"])
    assert log.stat().st_mode & 0o777 == 0o600
    assert "--- worker stdout ---" in log.read_text()
    assert not lifelock_left(run.row)


def test_capacity_guard(scenario: Scenario, git_pool: GitPool, treehouse_state: Path) -> None:
    scenario.configures(capacity={"max_workers": 1})
    scenario.starts()
    refused = scenario.refuses(dispatches("PROJ-2"))
    assert refused == [("refused:capacity", "1 of 1 workers are running")]
    assert "dispatch refused (capacity): 1 of 1 workers are running" in refused.said.text
    assert sum(s["status"] == "leased" for s in pool(treehouse_state)) == 1
    assert scenario.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 1


def test_one_worker_per_ticket(scenario: Scenario, git_pool: GitPool) -> None:
    scenario.starts()
    assert scenario.refuses(dispatches()) == [("refused:running", "run 1 is already working PROJ-1")]


@pytest.mark.parametrize("slug", ["Add", "a_b", "-a", "a-", "a--b", "a" * 41, "a/b", "a\n"])
def test_bad_slugs_are_refused_by_the_tool(scenario: Scenario, slug: str) -> None:
    said = scenario.overseer(dispatches(slug=slug), error=True)
    assert "slug" in said.text
    assert scenario.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


@pytest.mark.parametrize("mode", ["live", "dry run"])
@pytest.mark.parametrize("kind", [RunKind.IMPLEMENT, RunKind.RESUME])
@pytest.mark.parametrize(
    ("label", "reason"),
    [
        (None, "label is required: name the queue label you read on PROJ-1"),
        # The tracker source read the ticket, so the label is checked against what it observed (D051).
        (
            "agent-ready-someone-else",
            "'agent-ready-someone-else' was not on PROJ-1 when the tracker source last read it",
        ),
    ],
)
def test_dispatch_without_a_configured_label_is_unauthorized(
    scenario: Scenario,
    treehouse_state: Path,
    label: str | None,
    reason: str,
    kind: RunKind,
    mode: str,
) -> None:
    # The overseer must name a queue label, and only one configured and observed on the ticket passes (D051).
    conn = scenario.conn
    db.touch_ticket(conn, "PROJ-1", str(scenario.env.root))
    conn.execute("UPDATE tickets SET branch = 'agent/PROJ-1-work' WHERE key = 'PROJ-1'")  # so a resume could
    reasons = [ResumeReason.CI] if kind == RunKind.RESUME else []
    [(action, rationale)] = scenario.refuses(
        dispatches(kind=kind, label=label, reasons=reasons),
        dry_run=mode == "dry run",
    )
    assert action == "refused:unauthorized"
    assert rationale.startswith(reason)
    assert "agent-ready-tester" not in rationale  # the refusal never hands the overseer a label to copy
    assert not treehouse_state.exists()  # refused before leasing
    assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_unauthorized_is_checked_before_the_other_guards(scenario: Scenario, treehouse_state: Path) -> None:
    # No branch to continue, a slug a resume does not take, and a bad base: the missing label is still what is reported.
    def resume(label: str | None) -> Called:
        return dispatches(kind=RunKind.RESUME, label=label, reasons=[ResumeReason.CI], slug="again", base="main")

    assert [action for action, _ in scenario.refuses(resume(None))] == ["refused:unauthorized"]
    # With the label, the next guard in line refuses instead.
    assert [action for action, _ in scenario.refuses(resume(LABEL))][-1] == "refused:bad_slug"
    assert not treehouse_state.exists()


@pytest.mark.parametrize("mode", ["live", "dry run"])
def test_label_matches_case_insensitively_and_records_the_configured_spelling(
    scenario: Scenario,
    git_pool: GitPool,
    mode: str,
) -> None:
    # GitHub labels are case-insensitive, so an overseer that reads `Agent-Ready-Tester` has read the configured label.
    ticked = scenario.tick(dispatches(label="Agent-Ready-TESTER"), dry_run=mode == "dry run")
    assert ticked.actions == ["queried", "dispatch:implement"]
    assert ticked.decisions[1].rationale.endswith("; label agent-ready-tester")


def test_stale_worker_prompt_override_is_refused(scenario: Scenario, git_pool: GitPool, treehouse_state: Path) -> None:
    # An override written before D051 has no `{{LABELS}}`, so its worker would skip the label check: fail closed.
    overrides = scenario.env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text("Work {{KEY}} on {{BRANCH}}\n")
    [(action, rationale)] = scenario.refuses(dispatches())
    assert action == "refused:bad_prompt"
    assert "missing required placeholder {{LABELS}}" in rationale
    assert all(s["status"] == "available" for s in pool(treehouse_state))
    assert scenario.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_no_slot(scenario: Scenario, treehouse_state: Path) -> None:
    treehouse_state.write_text(pool_state(scenario.env.repo, [], max_trees=0))
    [(action, rationale)] = scenario.refuses(dispatches())
    assert action == "refused:no_slot"
    assert "max_trees" in rationale
    assert scenario.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_unparseable_lease_is_returned_and_refused(scenario: Scenario, treehouse_state: Path) -> None:
    # treehouse leased the slot, but its output lacks a field canopy needs: the slot goes back in the same dispatch.
    treehouse_state.write_text(json.dumps({"get_omit": ["base_branch"]}))
    [(action, rationale)] = scenario.refuses(dispatches())
    assert action == "refused:no_slot"
    assert "base_branch" in rationale
    assert "returned" in rationale
    assert all(s["status"] == "available" for s in pool(treehouse_state))
    assert scenario.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_bad_prompt_override_returns_the_slot(scenario: Scenario, git_pool: GitPool, treehouse_state: Path) -> None:
    overrides = scenario.env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text("Work {{KEY}} on {{BRNACH}}\n")
    [(action, rationale)] = scenario.refuses(dispatches())
    assert action == "refused:bad_prompt"
    assert "unknown placeholder {{BRNACH}}" in rationale
    assert all(s["status"] == "available" for s in pool(treehouse_state))
    assert scenario.conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_spawn_failure_returns_the_slot_and_closes_the_run(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    tracker_holds(conn)
    with in_tick(conn) as tick_id:
        runner = InlineRunner(spawn_error=procs.ProcError("no processes left"))
        said = overseer_calls(dispatches(), runner=runner)
        assert not said.error, said.text
        tick_starts(runner)
        assert decisions(conn, tick_id) == [("refused:spawn_failed", "no processes left")]
        run = present(db.get_run(conn, 1))
        assert run["status"] == "crashed"
        assert json.loads(run["result_json"]) == {"harness": "could not start the worker: no processes left"}
        assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_dry_run_still_starts_nothing(canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection) -> None:
    tracker_holds(conn)
    with in_tick(conn, dry_run=True):
        runner = InlineRunner()
        said = overseer_calls(dispatches(), runner=runner)
        assert not said.error, said.text
        assert runner.spawned == []
        assert not treehouse_state.exists()
        assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_dry_run_refuses_what_a_live_dispatch_would(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    with in_tick(conn) as earlier:

        def past_run(key: str, kind: str, status: str) -> None:
            db.touch_ticket(conn, key, str(canopy_env.root))
            run_id = db.insert_run(
                conn,
                tick_id=earlier,
                key=key,
                kind=kind,
                branch=f"agent/{key}-work",
                slots=[db.RunSlot("repo", Path("/pool/1"), f"lease-{key}", f"canopy:{key}", "main")],
                runs_dir=canopy_env.state_dir / "runs",
            )
            if status == "running":
                assert db.claim_run(conn, "runs", run_id, os.getpid())
            else:
                assert db.finish_run(conn, "runs", run_id, RunStatus(status), None)

        past_run("LIMIT", "implement", "done")
        past_run("LIMIT", "implement", "done")
        past_run("COOL", "fix-ci", "done")  # just ended, so a resume for CI alone is in its cooldown
        past_run("BUSY", "implement", "running")

    tracker_holds(conn, "LIMIT", "COOL", "BUSY", "NEW", "OTHER")
    with in_tick(conn, dry_run=True) as tick_id:
        runner = InlineRunner()
        for move, error in [
            (dispatches("LIMIT"), True),
            (dispatches("COOL", RunKind.RESUME, reasons=[ResumeReason.CI]), True),
            (dispatches("BUSY", RunKind.RESUME, reasons=[ResumeReason.CI]), True),
            (dispatches("NEW", RunKind.RESUME, reasons=[ResumeReason.CI]), True),
            (dispatches("NEW", base="main"), True),
            # BUSY and this one fill max_workers = 2
            (dispatches("NEW"), False),
            (dispatches("NEW"), True),
            (dispatches("OTHER"), True),
        ]:
            assert overseer_calls(move, runner=runner).error == error, move

        assert [(d.ticket_key, d.action) for d in db.decisions_for_tick(conn, tick_id)] == [
            ("LIMIT", "refused:attempt_limit"),
            ("LIMIT", "attention:attempt_limit"),
            ("COOL", "refused:cooldown"),
            ("BUSY", "refused:running"),
            ("NEW", "refused:no_branch"),
            ("NEW", "refused:bad_base"),
            ("NEW", "dispatch:implement"),
            ("NEW", "refused:running"),
            ("OTHER", "refused:capacity"),
        ]
        assert decisions(conn, tick_id)[-1][1] == "2 of 2 workers are running, counting 1 this dry run dispatched"
        assert runner.spawned == []
        assert not treehouse_state.exists()
        assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 4


def test_the_map_section_is_left_out_without_a_map_and_says_why_one_cannot_be_read(ctx: Context) -> None:
    assert dispatch.map_note(ctx) is None
    path = ctx.workspace.root / "MAP.md"
    path.write_text("  \n")
    assert dispatch.map_note(ctx) is None
    path.write_text("# map\n")
    assert dispatch.map_note(ctx) == "# map"
    # A map the planner cannot read is one it should know of, so its section stays, saying why.
    with mock.patch.object(Path, "read_text", autospec=True, side_effect=PermissionError(13, "Permission denied")):
        assert dispatch.map_note(ctx) == "MAP.md could not be read (Permission denied)."
