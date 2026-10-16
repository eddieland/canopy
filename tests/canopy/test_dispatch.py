"""`canopy dispatch` outside a dry run: guards, lease, and spawning `_run` (DESIGN §8)."""

import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import db
from canopy.core.vocab import RunStatus
from canopy.infra import procs
from tests.canopy.helpers import (
    InlineRunner,
    commit_and_push,
    in_tick,
    journal,
    lifelock_left,
    pool,
    slot_of,
    wait_for_run,
    worker_does,
)
from tests.conftest import CanopyEnv, GitPool, pool_state


@pytest.fixture
def conn(canopy_env: CanopyEnv) -> sqlite3.Connection:
    return journal(canopy_env)


def decisions(conn: sqlite3.Connection, tick_id: int) -> list[tuple[str, str]]:
    return [(d.action, d.rationale) for d in db.decisions_for_tick(conn, tick_id)]


def test_dispatch_leases_records_and_spawns(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    with in_tick(conn) as tick_id:
        runner = InlineRunner()
        assert (
            main(
                [
                    "dispatch",
                    "PROJ-1",
                    "--repo",
                    "repo",
                    "--label",
                    "agent-ready-tester",
                    "--kind",
                    "implement",
                    "--slug",
                    "add-login",
                ],
                runner=runner,
            )
            == 0
        )

        run = db.get_run(conn, 1)
        assert run is not None
        assert (run["ticket_key"], run["kind"], run["status"]) == ("PROJ-1", "implement", "running")
        assert run["branch"] == "agent/PROJ-1-add-login"
        assert run["pid"] == os.getpid()
        assert run["log_path"] == str(canopy_env.state_dir / "runs" / "1.log")
        leased = slot_of(conn, 1)
        assert (leased["repo"], leased["base_branch"], leased["lease_holder"]) == ("repo", "main", "canopy:PROJ-1")
        [slot] = [s for s in pool(treehouse_state) if s["status"] == "leased"]
        assert (slot["path"], slot["lease_id"]) == (leased["slot_path"], leased["lease_id"])

        assert runner.spawned == [(sys.executable, "-m", "canopy", "_run", "1")]
        [(action, rationale)] = decisions(conn, tick_id)
        assert action == "dispatch:implement"
        assert rationale == f"run 1: agent/PROJ-1-add-login in repo at {leased['slot_path']}; label agent-ready-tester"
        # The worker is told which labels authorize it, so it can check the ticket itself (D051).
        assert "`agent-ready-tester`" in (canopy_env.state_dir / "runs" / "1.prompt").read_text()
        ticket = conn.execute("SELECT * FROM tickets WHERE key = 'PROJ-1'").fetchone()
        assert ticket["branch"] == "agent/PROJ-1-add-login"

        prompt = canopy_env.state_dir / "runs" / "1.prompt"
        assert prompt.stat().st_mode & 0o777 == 0o600
        text = prompt.read_text()
        assert text.startswith("# canopy worker: implement")
        assert "{{" not in text
        assert f"ticket PROJ-1 in {leased['slot_path']}." in text
        assert "This run works in one repository:\n- `repo` at `" + str(leased["slot_path"]) in text
        assert ": branch `agent/PROJ-1-add-login` from `main`; PR: not recorded; look up the PR for " in text
        assert '"prs":{"repo":"<url or null>"}' in text
        assert "the label `agent`" in text
        assert "Time limit: 45 minutes" in text


def test_worker_is_told_the_configured_needs_human_label(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    canopy_env.write_shared(canopy_env.shared_file.read_text() + 'needs_human_label = "blocked-on-team"\n')
    with in_tick(conn):
        args = ["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"]
        assert main(args, runner=InlineRunner()) == 0
        text = (canopy_env.state_dir / "runs" / "1.prompt").read_text()
        assert "Add the label `blocked-on-team` to the ticket" in text
        assert "needs-human" not in text


def test_worker_is_told_the_configured_comment_marks(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    canopy_env.write_user(
        canopy_env.user_file.read_text()
        + '\n[trust]\ncomment_prefix = "[bot]"\ncomment_suffix = "Posted by canopy for alice."\n'
    )
    with in_tick(conn):
        args = ["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"]
        assert main(args, runner=InlineRunner()) == 0
        text = (canopy_env.state_dir / "runs" / "1.prompt").read_text()
        assert "start it with `[bot]` and a space, and end it with `Posted by canopy for alice.`" in text
        assert (
            "a comment that starts with `[bot]` and ends with `Posted by canopy for alice.` outside any quote" in text
        )
        assert "CANOPY:" not in text


def test_worker_opens_prs_through_the_mcp_or_the_configured_skill(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    with in_tick(conn):
        args = ["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"]
        assert main(args, runner=InlineRunner()) == 0
        assert (
            "Never target another branch. Open each PR through the GitHub MCP."
            in (canopy_env.state_dir / "runs" / "1.prompt").read_text()
        )

        # The operator's own skill replaces the MCP, with no fallback to it.
        canopy_env.write_user(
            canopy_env.user_file.read_text().replace("[runtime]\n", "[runtime]\npr_skill = 'acme-pr'\n")
        )
        assert main(["dispatch", "PROJ-2", "--repo", "repo", *args[2:]], runner=InlineRunner()) == 0
        text = (canopy_env.state_dir / "runs" / "2.prompt").read_text()
        assert "Never target another branch. Open each PR by following the skill `acme-pr`, and in no other way" in text
        assert "Open each PR through the GitHub MCP" not in text


def test_an_override_that_ignores_the_pr_skill_is_refused(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text("Work {{KEY}} for {{LABELS}}; open a PR through the GitHub MCP\n")
    canopy_env.write_user(canopy_env.user_file.read_text().replace("[runtime]\n", "[runtime]\npr_skill = 'acme-pr'\n"))
    with in_tick(conn) as tick_id:
        assert (
            main(
                ["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"],
                runner=InlineRunner(),
            )
            == 1
        )
        [(action, rationale)] = decisions(conn, tick_id)
        assert action == "refused:bad_prompt"
        assert "missing required placeholder {{OPEN_PR}}" in rationale
        assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_detached_run_finishes_on_its_own(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    with worker_does(*commit_and_push("agent/PROJ-1-work")), in_tick(conn):
        assert (
            main(["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"]) == 0
        )
        run = wait_for_run(conn, 1)
        assert run["status"] == "done", Path(run["log_path"]).read_text()
        assert git_pool.remote_head("agent/PROJ-1-work") is not None
        assert all(s["status"] == "available" for s in pool(treehouse_state))
        log = Path(run["log_path"])
        assert log.stat().st_mode & 0o777 == 0o600
        assert "--- worker stdout ---" in log.read_text()
        assert not lifelock_left(run)


def test_capacity_guard(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    canopy_env.write_user(canopy_env.user_file.read_text() + "\n[capacity]\nmax_workers = 1\n")
    with in_tick(conn) as tick_id:
        runner = InlineRunner()
        assert (
            main(
                ["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"],
                runner=runner,
            )
            == 0
        )
        assert (
            main(
                ["dispatch", "PROJ-2", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"],
                runner=runner,
            )
            == 1
        )
        assert "dispatch refused (capacity): 1 of 1 workers are running" in capsys.readouterr().err
        assert decisions(conn, tick_id)[1] == ("refused:capacity", "1 of 1 workers are running")
        assert sum(s["status"] == "leased" for s in pool(treehouse_state)) == 1
        assert len(runner.spawned) == 1


def test_one_worker_per_ticket(canopy_env: CanopyEnv, git_pool: GitPool, conn: sqlite3.Connection) -> None:
    with in_tick(conn) as tick_id:
        runner = InlineRunner()
        assert (
            main(
                ["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"],
                runner=runner,
            )
            == 0
        )
        assert (
            main(
                ["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"],
                runner=runner,
            )
            == 1
        )
        assert decisions(conn, tick_id)[1] == ("refused:running", "run 1 is already working PROJ-1")


@pytest.mark.parametrize("slug", ["Add", "a_b", "-a", "a-", "a--b", "a" * 41, "a/b", "a\n"])
def test_bad_slugs_are_usage_errors(canopy_env: CanopyEnv, conn: sqlite3.Connection, slug: str) -> None:
    with in_tick(conn):
        assert (
            main(
                [
                    "dispatch",
                    "PROJ-1",
                    "--repo",
                    "repo",
                    "--label",
                    "agent-ready-tester",
                    "--kind",
                    "implement",
                    "--slug",
                    slug,
                ],
                runner=InlineRunner(),
            )
            == 2
        )


@pytest.mark.parametrize("mode", ["live", "dry run"])
@pytest.mark.parametrize("kind", ["implement", "fix-ci", "resume"])
@pytest.mark.parametrize(
    ("label", "reason"),
    [
        (None, "--label is required: name the queue label you read on PROJ-1"),
        ("agent-ready-someone-else", "'agent-ready-someone-else' is not a configured queue label"),
    ],
)
def test_dispatch_without_a_configured_label_is_unauthorized(
    canopy_env: CanopyEnv,
    treehouse_state: Path,
    conn: sqlite3.Connection,
    label: str | None,
    reason: str,
    kind: str,
    mode: str,
) -> None:
    # canopy cannot read labels; the overseer must name the one it read, and only a configured one passes (D051).
    db.touch_ticket(conn, "PROJ-1", str(canopy_env.root))
    conn.execute("UPDATE tickets SET branch = 'agent/PROJ-1-work' WHERE key = 'PROJ-1'")  # so fix-ci and resume could
    with in_tick(conn, dry_run=mode == "dry run") as tick_id:
        args = ["dispatch", "PROJ-1", "--repo", "repo", "--kind", kind] + ([] if label is None else ["--label", label])
        assert main(args, runner=InlineRunner()) == 1
        [(action, rationale)] = decisions(conn, tick_id)
        assert action == "refused:unauthorized"
        assert rationale.startswith(reason)
        assert "agent-ready-tester" not in rationale  # the refusal never hands the overseer a label to copy
        assert not treehouse_state.exists()  # refused before leasing
        assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_unauthorized_is_checked_before_the_other_guards(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection
) -> None:
    # No branch to continue, a slug fix-ci does not take, and a bad base: the missing label is still what is reported.
    with in_tick(conn) as tick_id:
        args = ["dispatch", "PROJ-1", "--repo", "repo", "--kind", "fix-ci", "--slug", "again", "--base", "main"]
        assert main(args, runner=InlineRunner()) == 1
        assert [action for action, _ in decisions(conn, tick_id)] == ["refused:unauthorized"]
        # With the label, the next guard in line refuses instead.
        assert main([*args, "--label", "agent-ready-tester"], runner=InlineRunner()) == 1
        assert [action for action, _ in decisions(conn, tick_id)][-1] == "refused:bad_slug"
        assert not treehouse_state.exists()


@pytest.mark.parametrize("mode", ["live", "dry run"])
def test_label_matches_case_insensitively_and_records_the_configured_spelling(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    conn: sqlite3.Connection,
    mode: str,
) -> None:
    # GitHub labels are case-insensitive, so an overseer that reads `Agent-Ready-Tester` has read the configured label.
    with in_tick(conn, dry_run=mode == "dry run") as tick_id:
        assert (
            main(
                ["dispatch", "PROJ-1", "--repo", "repo", "--label", "Agent-Ready-TESTER", "--kind", "implement"],
                runner=InlineRunner(),
            )
            == 0
        )
        [(action, rationale)] = decisions(conn, tick_id)
        assert action == "dispatch:implement"
        assert rationale.endswith("; label agent-ready-tester")


def test_stale_worker_prompt_override_is_refused(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    # An override written before D051 has no `{{LABELS}}`, so its worker would skip the label check: fail closed.
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text("Work {{KEY}} on {{BRANCH}}\n")
    with in_tick(conn) as tick_id:
        assert (
            main(
                ["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"],
                runner=InlineRunner(),
            )
            == 1
        )
        [(action, rationale)] = decisions(conn, tick_id)
        assert action == "refused:bad_prompt"
        assert "missing required placeholder {{LABELS}}" in rationale
        assert all(s["status"] == "available" for s in pool(treehouse_state))
        assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_no_slot(canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection) -> None:
    treehouse_state.write_text(pool_state(canopy_env.repo, [], max_trees=0))
    with in_tick(conn) as tick_id:
        assert (
            main(
                ["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"],
                runner=InlineRunner(),
            )
            == 1
        )
        [(action, rationale)] = decisions(conn, tick_id)
        assert action == "refused:no_slot"
        assert "max_trees" in rationale
        assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_unparseable_lease_is_returned_and_refused(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection
) -> None:
    # treehouse leased the slot, but its output lacks a field canopy needs: the slot goes back in the same dispatch.
    treehouse_state.write_text(json.dumps({"get_omit": ["base_branch"]}))
    with in_tick(conn) as tick_id:
        assert (
            main(
                ["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"],
                runner=InlineRunner(),
            )
            == 1
        )
        [(action, rationale)] = decisions(conn, tick_id)
        assert action == "refused:no_slot"
        assert "base_branch" in rationale
        assert "returned" in rationale
        assert all(s["status"] == "available" for s in pool(treehouse_state))
        assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_bad_prompt_override_returns_the_slot(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text("Work {{KEY}} on {{BRNACH}}\n")
    with in_tick(conn) as tick_id:
        assert (
            main(
                ["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"],
                runner=InlineRunner(),
            )
            == 1
        )
        [(action, rationale)] = decisions(conn, tick_id)
        assert action == "refused:bad_prompt"
        assert "unknown placeholder {{BRNACH}}" in rationale
        assert all(s["status"] == "available" for s in pool(treehouse_state))
        assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_spawn_failure_returns_the_slot_and_closes_the_run(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
    conn: sqlite3.Connection,
) -> None:
    with in_tick(conn) as tick_id:
        runner = InlineRunner(spawn_error=procs.ProcError("no processes left"))
        assert (
            main(
                ["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"],
                runner=runner,
            )
            == 1
        )
        assert decisions(conn, tick_id) == [("refused:spawn_failed", "no processes left")]
        run = db.get_run(conn, 1)
        assert run is not None
        assert run["status"] == "crashed"
        assert json.loads(run["result_json"]) == {"harness": "could not start the worker: no processes left"}
        assert all(s["status"] == "available" for s in pool(treehouse_state))


def test_dry_run_still_starts_nothing(canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection) -> None:
    with in_tick(conn, dry_run=True):
        runner = InlineRunner()
        assert (
            main(
                ["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"],
                runner=runner,
            )
            == 0
        )
        assert runner.spawned == []
        assert not treehouse_state.exists()
        assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_dry_run_refuses_what_a_live_dispatch_would(
    canopy_env: CanopyEnv, treehouse_state: Path, conn: sqlite3.Connection
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

        past_run("LIMIT", "fix-ci", "done")
        past_run("LIMIT", "fix-ci", "done")
        past_run("COOL", "fix-ci", "done")  # just ended, so fix-ci is in its cooldown
        past_run("BUSY", "implement", "running")

    with in_tick(conn, dry_run=True) as tick_id:
        runner = InlineRunner()
        for args, code in [
            (["LIMIT", "--label", "agent-ready-tester", "--kind", "fix-ci"], 1),
            (["COOL", "--label", "agent-ready-tester", "--kind", "fix-ci"], 1),
            (["BUSY", "--label", "agent-ready-tester", "--kind", "resume"], 1),
            (["NEW", "--label", "agent-ready-tester", "--kind", "fix-ci"], 1),
            (["NEW", "--label", "agent-ready-tester", "--kind", "implement", "--base", "main"], 1),
            # BUSY and this one fill max_workers = 2
            (["NEW", "--label", "agent-ready-tester", "--kind", "implement"], 0),
            (["NEW", "--label", "agent-ready-tester", "--kind", "implement"], 1),
            (["OTHER", "--label", "agent-ready-tester", "--kind", "implement"], 1),
        ]:
            assert main(["dispatch", "--repo", "repo", *args], runner=runner) == code, args

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
