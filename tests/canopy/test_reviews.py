"""Reviews (DESIGN §21, ROADMAP M11): a fresh reviewer per PR commit, guarded, in a slot it never works in."""

import json
import os
import signal
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import conversation, db, review_diff
from canopy.core import review_result as result
from canopy.core.config import load
from canopy.core.vocab import ReviewRunStatus
from canopy.infra import procs
from canopy.loop import attention
from tests.canopy.helpers import InlineRunner, commit_and_push, in_tick, journal, lifelock_left, pool, worker_does
from tests.canopy.test_private import operator
from tests.conftest import CanopyEnv, GitPool, git

PR = "https://github.com/acme/api/pull/7"
FINDINGS = {
    "status": "done",
    "verdict": "findings",
    "impact": "normal",
    "summary": "One blocking defect.",
    "findings": [
        {
            "severity": "blocking",
            "title": "retry never stops",
            "location": "src/retry.py:42",
            "detail": "The loop resets attempts on every error.\nA failing call retries forever.",
        }
    ],
}
CLEAN = {"status": "done", "verdict": "clean", "impact": "low", "summary": "Nothing found."}


@pytest.fixture
def reviews(canopy_env: CanopyEnv) -> CanopyEnv:
    """Reviews on, for the loop's own PRs, with the reviewer command running the fake agent as `canopy-reviewer`.

    PROJ-1's unit in `repo` has opened `PR`, as its worker's result records it, so a review may name PROJ-1 for it.
    """
    template = "env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-reviewer {prompt}"
    user = canopy_env.user_file.read_text().replace("[runtime]\n", f"[runtime]\nreview_cmd = '{template}'\n", 1)
    canopy_env.write_user(user + "\n[review]\nagent_prs = true\n")
    db.set_unit(canopy_env.journal(), "PROJ-1", str(canopy_env.root), "repo", pr_url=PR)
    return canopy_env


def head(git_pool: GitPool) -> str:
    return git("rev-parse", "main", cwd=git_pool.origin)


def review(*args: str, sha: str, pr: str = PR) -> list[str]:
    return ["review", "run", "--pr", pr, "--sha", sha, "--repo", "repo", *args]


def decisions(conn: sqlite3.Connection, tick_id: int) -> list[tuple[str | None, str | None, str, str]]:
    return [(d.ticket_key, d.pr, d.action, d.rationale) for d in db.decisions_for_tick(conn, tick_id)]


@contextmanager
def reviewer_reports(report: object, *commands: list[str]) -> Iterator[None]:
    """Until the block ends, the fake reviewer runs `commands` and then prints `report`."""
    with mock.patch.dict(
        os.environ,
        {
            "FAKE_REVIEWER_RESULT": report if isinstance(report, str) else json.dumps(report),
            "FAKE_REVIEWER_COMMANDS": json.dumps(list(commands)),
        },
    ):
        yield


def run_inline(
    conn: sqlite3.Connection,
    *args: str,
    sha: str,
    pr: str = PR,
    runner: InlineRunner | None = None,
) -> int:
    """Start a review in its own tick and do its `_review` in this process, as the detached one would."""
    with in_tick(conn) as tick_id:
        assert main(review(*args, sha=sha, pr=pr), runner=InlineRunner()) == 0
        run_id = int(conn.execute("SELECT max(id) FROM review_runs").fetchone()[0])
        assert main(["_review", str(run_id)], runner=runner or InlineRunner()) == 0
        db.finish_tick(conn, tick_id, "ok", "test")
    return run_id


def state_block(agent_log: Path) -> dict[str, Any]:
    overseer = json.loads(agent_log.read_text().splitlines()[-1])
    state: dict[str, Any] = json.loads(overseer["argv"][3].split("```json\n", 1)[1].split("\n```", 1)[0])
    return state


def test_with_reviews_off_nothing_about_them_reaches_the_overseer(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path
) -> None:
    with mock.patch.dict(os.environ, {"FAKE_AGENT_RESULT": "CANOPY_TICK_DONE"}):
        assert main(["tick", "--dry-run"]) == 0
        assert "reviews" not in state_block(agent_log)
        conn = journal(canopy_env)
        with in_tick(conn) as tick_id:
            assert main(review(sha="a" * 40), runner=InlineRunner()) == 1
            assert [d[2] for d in decisions(conn, tick_id)] == ["refused:reviews_off"]


def test_max_reviews_zero_turns_reviews_off(reviews: CanopyEnv, treehouse_state: Path, agent_log: Path) -> None:
    reviews.write_user(reviews.user_file.read_text() + "\n[capacity]\nmax_reviews = 0\n")
    with mock.patch.dict(os.environ, {"FAKE_AGENT_RESULT": "CANOPY_TICK_DONE"}):
        assert main(["tick", "--dry-run"]) == 0
        assert "reviews" not in state_block(agent_log)


def test_a_review_runs_outside_the_checkout_at_the_commit(
    reviews: CanopyEnv, git_pool: GitPool, agent_log: Path
) -> None:
    """M11 against the fakes: the reviewer reads the checkout at the commit through a link, and the slot goes back."""
    conn = journal(reviews)
    sha = head(git_pool)
    with (
        in_tick(conn) as tick_id,
        reviewer_reports(FINDINGS, ["git", "-C", "checkout", "rev-parse", "HEAD"], ["pwd"]),
    ):
        assert main(review("--ticket", "PROJ-1", "--context", "Start with src/retry.py", sha=sha)) == 0
        deadline = time.monotonic() + 30
        row = db.get_review_run(conn, 1)
        while row is not None and row["status"] == "running" and time.monotonic() < deadline:
            time.sleep(0.05)
            row = db.get_review_run(conn, 1)
        assert row is not None
        assert row["status"] == "done", Path(row["log_path"]).read_text()
        assert result.stored(row["result_json"]) == result.ReviewResult.model_validate(FINDINGS)
        assert (row["pr_url"], row["sha"], row["ticket_key"]) == (PR, sha, "PROJ-1")

        [reviewer] = [json.loads(line) for line in agent_log.read_text().splitlines()]
        run_dir = reviews.state_dir / "reviews" / "1"
        assert reviewer["cwd"] == str(run_dir)
        assert reviewer["argv"][:3] == ["run", "--agent", "canopy-reviewer"]
        assert "CANOPY_TICK_ID" not in reviewer["env"]
        checked, _ = reviewer["commands"]
        assert checked["stdout"].strip() == sha
        assert not run_dir.exists()  # removed, and its link with it, once the run ended
        assert not lifelock_left(row)
        assert [s["status"] for s in pool(Path(os.environ["FAKE_TREEHOUSE_STATE"]))] == ["available", "available"]
        [(ticket, pr, action, rationale)] = decisions(conn, tick_id)
        assert (ticket, pr, action) == ("PROJ-1", PR, "dispatch:review")
        assert rationale.startswith(f"review run 1: {sha} in ")
        assert rationale.endswith("; context=Start with src/retry.py")

        prompt = reviewer["argv"][3]
        assert prompt.startswith("# canopy reviewer\n")
        assert f"- Checkout: `{run_dir / 'checkout'}` is the repository at that commit." in prompt
        assert "Post nothing anywhere" in prompt
        assert "canopy-review" not in prompt
        assert "None: never report `low`." in prompt
        assert prompt.rstrip().endswith(result.CONTRACT)


def test_a_review_hears_the_notice_in_force(reviews: CanopyEnv, git_pool: GitPool, agent_log: Path) -> None:
    # A review reads CI too, so the operator's notice about an outage reaches it (DESIGN §8, §21).
    conn = journal(reviews)
    assert main(["notice", "CI is down."]) == 0
    with reviewer_reports(CLEAN):
        run_id = run_inline(conn, sha=head(git_pool))
    prompt = (reviews.state_dir / "reviews" / f"{run_id}.prompt").read_text()
    assert "## Notice from the operator\n\nCI is down.\n" in prompt


@pytest.mark.parametrize(
    ("args", "sha", "reason"),
    [
        (["--pr", "http://x.test/pull/1"], "a" * 40, "--pr must be the PR's plain https:// URL"),
        ([], "abc", "--sha must be the full head commit"),
        ([], "A" * 40, "--sha must be the full head commit"),
    ],
)
def test_bad_pr(reviews: CanopyEnv, args: list[str], sha: str, reason: str) -> None:
    conn = journal(reviews)
    with in_tick(conn) as tick_id:
        command = ["review", "run", *(args or ["--pr", PR]), "--sha", sha, "--repo", "repo"]
        assert main(command, runner=InlineRunner()) == 1
        [(_, _, action, rationale)] = decisions(conn, tick_id)
        assert action == "refused:bad_pr"
        assert rationale.startswith(reason)


def test_review_guards(reviews: CanopyEnv, git_pool: GitPool, agent_log: Path) -> None:
    reviews.write_user(reviews.user_file.read_text() + "\n[policy]\nmax_reviews_per_pr = 2\n")
    conn = journal(reviews)
    sha = head(git_pool)
    other = "b" * 40
    with in_tick(conn) as tick_id:
        runner = InlineRunner()
        # Started, never run: it stays running.
        assert main(review(sha=sha), runner=runner) == 0
        assert main(review(sha=sha), runner=runner) == 1  # running
        assert main(review(sha=sha, pr=f"{PR}0"), runner=runner) == 1  # review_capacity: max_reviews is 1
        assert db.finish_run(conn, "review_runs", 1, ReviewRunStatus.DONE, json.dumps(CLEAN))
        assert runner.run(
            ["treehouse", "return", "--force", str(pool(Path(os.environ["FAKE_TREEHOUSE_STATE"]))[0]["path"])]
        ).ok
        assert main(review(sha=sha), runner=runner) == 1  # reviewed
        assert main(review(sha=other), runner=runner) == 0
        assert db.finish_run(conn, "review_runs", 2, ReviewRunStatus.FAILED, "{}")
        assert runner.run(
            ["treehouse", "return", "--force", str(pool(Path(os.environ["FAKE_TREEHOUSE_STATE"]))[0]["path"])]
        ).ok
        assert main(review(sha="c" * 40), runner=runner) == 1  # review_limit
        actions = [d[2] for d in decisions(conn, tick_id)]
        assert actions == [
            "dispatch:review",
            "refused:running",
            "refused:review_capacity",
            "refused:reviewed",
            "dispatch:review",
            "refused:review_limit",
            "attention:review_limit",
        ]
        reasons = {d[2]: d[3] for d in decisions(conn, tick_id)}
        assert reasons["refused:reviewed"] == (
            f"review run 1 already reviewed {sha[:12]} (clean, impact low); one review per commit"
        )
        assert reasons["refused:review_limit"] == "this PR has had 2 review runs and the limit is 2"
        assert reasons["attention:review_limit"] == (
            f"this PR has had 2 review runs and the limit is 2; allow it another review with `canopy grant {PR} review`"
        )


def test_a_grant_lets_a_pr_at_its_review_limit_be_reviewed_again_and_every_run_still_counts(
    reviews: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reviews.write_user(reviews.user_file.read_text() + "\n[policy]\nmax_reviews_per_pr = 1\n")
    conn = journal(reviews)
    with reviewer_reports(CLEAN):
        run_inline(conn, sha=head(git_pool))
        run_inline(conn, sha=head(git_pool), pr=f"{PR}0")
        with in_tick(conn) as tick_id:
            assert main(review(sha="b" * 40), runner=InlineRunner()) == 1
            assert [d[2] for d in decisions(conn, tick_id)] == ["refused:review_limit", "attention:review_limit"]
            db.finish_tick(conn, tick_id, "ok", "test")

        assert operator("grant", PR, "review") == 0
        assert f"{PR} has had 1 review runs, and may now have 2." in capsys.readouterr().out
        run_id = run_inline(conn, sha="b" * 40)
    prompt = " ".join((reviews.state_dir / "reviews" / f"{run_id}.prompt").read_text().split())
    assert "This is review 2 of at most 2 of this PR." in prompt

    # The granted run counted like any other, and the grant is that PR's only.
    with in_tick(conn) as tick_id:
        assert main(review(sha="c" * 40), runner=InlineRunner()) == 1
        assert main(review(sha="c" * 40, pr=f"{PR}0"), runner=InlineRunner()) == 1
        reasons = [(d[1], d[3]) for d in decisions(conn, tick_id) if d[2] == "refused:review_limit"]
        assert reasons == [
            (PR, "this PR has had 2 review runs and the limit is 2"),
            (f"{PR}0", "this PR has had 1 review runs and the limit is 1"),
        ]
        db.finish_tick(conn, tick_id, "ok", "test")
    assert operator("grant", PR, "review", "--runs", "2") == 0
    assert "has had 2 review runs, and may now have 4." in capsys.readouterr().out

    # The state block shows a granted PR's grants beside its review runs; a PR with none has no key.
    with mock.patch.dict(os.environ, {"FAKE_OVERSEER_RESULT": "CANOPY_TICK_DONE"}):
        assert main(["tick", "--dry-run"]) == 0
    prs = {p["url"]: p for p in state_block(agent_log)["reviews"]["prs"]}
    assert (prs[PR]["review_runs"], prs[PR]["granted"]) == (2, 3)
    assert "granted" not in prs[f"{PR}0"]


@pytest.mark.parametrize("env", ["CANOPY_TICK_ID", "CANOPY_RUN_ID"])
def test_only_the_operator_grants_reviews(
    reviews: CanopyEnv,
    git_pool: GitPool,
    capsys: pytest.CaptureFixture[str],
    env: str,
) -> None:
    conn = journal(reviews)
    with reviewer_reports(CLEAN):
        run_inline(conn, sha=head(git_pool))
    capsys.readouterr()
    in_run: dict[str, str] = {"CANOPY_RUN_ID": "1"} if env == "CANOPY_RUN_ID" else {}
    with in_tick(conn) as tick_id, mock.patch.dict(os.environ, in_run):
        if env == "CANOPY_RUN_ID":
            os.environ.pop("CANOPY_TICK_ID")
        assert main(["grant", PR, "review"]) == 1
        assert "grant refused (inside_run)" in capsys.readouterr().err
        db.finish_tick(conn, tick_id, "ok", "test")
    assert conn.execute("SELECT count(*) FROM review_grants").fetchone()[0] == 0


def test_review_grant_refusals(
    reviews: CanopyEnv,
    git_pool: GitPool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = journal(reviews)
    assert operator("grant", PR, "review") == 1
    assert f"grant refused (unknown): canopy has not reviewed {PR}" in capsys.readouterr().err
    with reviewer_reports(CLEAN):
        run_inline(conn, sha=head(git_pool))
    capsys.readouterr()
    refusals = [
        (["repo#7", "review"], "grant refused (bad_ref): name the PR by its URL"),
        (["PROJ-1", "review"], "grant refused (bad_kind): PROJ-1 is a ticket; `review` takes the PR's URL"),
        ([PR, "implement"], f"grant refused (bad_kind): {PR} is a PR, which takes only `review`"),
        ([PR, "review", "--repo", "repo"], "grant refused (bad_repo): a PR's review limit is the PR's own"),
    ]
    for args, refusal in refusals:
        assert operator("grant", *args) == 1
        assert refusal in capsys.readouterr().err
    assert operator("grant", PR, "review", "--runs", "0") == 2
    assert conn.execute("SELECT count(*) FROM review_grants").fetchone()[0] == 0


def test_a_review_waits_for_its_tickets_worker_and_counts_against_max_workers(
    reviews: CanopyEnv, git_pool: GitPool, agent_log: Path
) -> None:
    reviews.write_user(reviews.user_file.read_text() + "\n[capacity]\nmax_workers = 1\nmax_reviews = 2\n")
    conn = journal(reviews)
    with in_tick(conn) as tick_id:
        runner = InlineRunner()
        dispatch = ["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"]
        assert main(dispatch, runner=runner) == 0
        assert main(review("--ticket", "PROJ-1", sha=head(git_pool)), runner=runner) == 1
        assert main(review(sha=head(git_pool), pr=f"{PR}0"), runner=runner) == 1
        [(_, _, a1, r1), (_, _, a2, r2)] = decisions(conn, tick_id)[1:]
        assert (a1, r1) == ("refused:running", "a worker run for PROJ-1 is running; review its PR once it ends")
        assert (a2, r2) == ("refused:capacity", "1 of 1 workers and reviews are running")


def test_a_running_review_takes_worker_capacity(reviews: CanopyEnv, git_pool: GitPool, agent_log: Path) -> None:
    reviews.write_user(reviews.user_file.read_text() + "\n[capacity]\nmax_workers = 1\n")
    conn = journal(reviews)
    with in_tick(conn) as tick_id:
        runner = InlineRunner()
        assert main(review(sha=head(git_pool)), runner=runner) == 0
        assert (
            main(
                ["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"],
                runner=runner,
            )
            == 1
        )
        assert decisions(conn, tick_id)[-1][2:] == ("refused:capacity", "1 of 1 workers are running")


def test_a_dry_run_counts_its_reviews(reviews: CanopyEnv) -> None:
    conn = journal(reviews)
    with in_tick(conn, dry_run=True) as tick_id:
        runner = InlineRunner()
        assert main(review(sha="a" * 40), runner=runner) == 0
        assert main(review(sha="a" * 40), runner=runner) == 1
        assert main(review(sha="a" * 40, pr=f"{PR}0"), runner=runner) == 1
        assert [d[2:] for d in decisions(conn, tick_id)] == [
            ("dispatch:review", f"dry run: not dispatched; would review {'a' * 40}"),
            ("refused:running", "this dry run already reviewed this PR"),
            ("refused:review_capacity", "1 of 1 review runs are running"),
        ]
        assert runner.spawned == []
        assert conn.execute("SELECT count(*) FROM review_runs").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("report", "status", "note"),
    [
        # A reviewer from before reviews stayed in canopy may still name a comment: it is ignored (D114).
        ({**FINDINGS, "comment": f"{PR}#issuecomment-1"}, "done", ""),
        (CLEAN, "done", "reported low impact, but review.low_impact is not set; recorded as normal"),
        ({**CLEAN, "findings": FINDINGS["findings"]}, "unknown", "the reviewer's last line was not a valid result"),
        ({"status": "failed", "summary": "cannot read the PR"}, "failed", ""),
    ],
)
def test_the_harness_checks_what_it_can_of_a_result(
    reviews: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    report: dict[str, object],
    status: str,
    note: str,
) -> None:
    conn = journal(reviews)
    with reviewer_reports(report):
        run_id = run_inline(conn, sha=head(git_pool))
        row = db.get_review_run(conn, run_id)
        assert row is not None
        assert row["status"] == status
        stored = json.loads(row["result_json"])
        assert stored.get("harness", "").startswith(note)
        if status == "done":
            assert stored["impact"] == "normal"


@pytest.mark.parametrize("events", [False, True])
def test_a_plugin_notice_after_the_result_does_not_hide_it(
    reviews: CanopyEnv, git_pool: GitPool, agent_log: Path, *, events: bool
) -> None:
    # A plugin the operator must load prints after the agent's last word; it lands in the text (DESIGN §13).
    if events:
        text = reviews.user_file.read_text()
        reviews.write_user(
            text.replace("--agent canopy-reviewer {prompt}", "--agent canopy-reviewer --format json {prompt}")
        )
    conn = journal(reviews)
    with reviewer_reports(f"{json.dumps(FINDINGS)}\n[policy-plugin] session audited, 0 violations"):
        row = db.get_review_run(conn, run_inline(conn, sha=head(git_pool)))
        assert row is not None
        assert row["status"] == "done"
        assert json.loads(row["result_json"])["verdict"] == "findings"


def test_links_out_of_the_checkout_are_removed_before_the_reviewer_reads_it(
    reviews: CanopyEnv, git_pool: GitPool, agent_log: Path, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("operator only\n")
    work = git_pool.slots[1]
    git("checkout", "--quiet", "-b", "pr-7", "origin/main", cwd=work)
    (work / "inside").symlink_to("README.md" if (work / "README.md").exists() else ".")
    (work / "outside").symlink_to(secret)
    (work / "up").symlink_to("../..")
    git("add", "inside", "outside", "up", cwd=work)
    git("commit", "--quiet", "-m", "links", cwd=work)
    git("push", "--quiet", "origin", "pr-7", cwd=work)
    sha = git("rev-parse", "HEAD", cwd=work)
    git("checkout", "--quiet", "--detach", cwd=work)
    with reviewer_reports(FINDINGS, ["ls", "checkout/"]):
        run_id = run_inline(conn := journal(reviews), sha=sha)
        row = db.get_review_run(conn, run_id)
        assert row is not None
        assert row["status"] == "done", Path(row["log_path"]).read_text()
        [reviewer] = [json.loads(line) for line in agent_log.read_text().splitlines()]
        [listing] = reviewer["commands"]
        names = listing["stdout"].split()
        assert "inside" in names
        assert "outside" not in names
        assert "up" not in names


@pytest.mark.parametrize("phase", ["review_pending", "review_findings"])
def test_the_review_phases_are_a_units(reviews: CanopyEnv, phase: str) -> None:
    conn = journal(reviews)
    with in_tick(conn):
        assert main(["ticket", "set", "PROJ-1", "--repo", "repo", "--phase", phase]) == 0
        [unit] = db.units(conn, "PROJ-1")
        assert unit["phase"] == phase


def test_a_commit_origin_does_not_have_fails_the_review(reviews: CanopyEnv, git_pool: GitPool, agent_log: Path) -> None:
    """A PR of another repository fails here: its commit cannot be fetched from this one's origin."""
    conn = journal(reviews)
    run_id = run_inline(conn, sha="d" * 40)
    row = db.get_review_run(conn, run_id)
    assert row is not None
    assert row["status"] == "failed"
    assert json.loads(row["result_json"])["harness"].startswith("git fetch failed: ")
    assert not agent_log.exists()  # the reviewer never ran
    assert [s["status"] for s in pool(Path(os.environ["FAKE_TREEHOUSE_STATE"]))] == ["available", "available"]


def test_a_killed_review_is_crashed_on_the_next_tick(reviews: CanopyEnv, git_pool: GitPool, agent_log: Path) -> None:
    conn = journal(reviews)
    with mock.patch.dict(os.environ, {"FAKE_REVIEWER_SLEEP": "60"}):
        with in_tick(conn) as tick_id:
            assert main(review(sha=head(git_pool))) == 0
            db.finish_tick(conn, tick_id, "ok", "test")
        deadline = time.monotonic() + 30
        row = db.get_review_run(conn, 1)
        while (row is None or row["agent_pid"] is None) and time.monotonic() < deadline:
            time.sleep(0.05)
            row = db.get_review_run(conn, 1)
        assert row is not None
        assert row["agent_pid"] is not None, "`_review` never started the reviewer"
        pid, agent_pid = int(row["pid"]), int(row["agent_pid"])
        run_dir = reviews.state_dir / "reviews" / "1"
        assert (run_dir / "checkout").is_symlink()
        os.kill(pid, signal.SIGKILL)
        while procs.alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        treehouse_state = Path(os.environ["FAKE_TREEHOUSE_STATE"])
        assert [s["status"] for s in pool(treehouse_state)] == ["leased", "available"]

        with mock.patch.dict(os.environ, {"FAKE_OVERSEER_RESULT": "CANOPY_TICK_DONE"}):
            assert main(["tick"]) == 0
            crashed = db.get_review_run(conn, 1)
            assert crashed is not None
            assert crashed["status"] == "crashed"
            assert not procs.lifelock(Path(crashed["log_path"])).exists()
            while procs.alive(agent_pid) and time.monotonic() < deadline:
                time.sleep(0.05)
            assert not procs.alive(agent_pid)
            assert [s["status"] for s in pool(treehouse_state)] == ["available", "available"]
            assert not run_dir.exists()
            assert git_pool.slots[0].is_dir()  # removing the run's directory never follows its link


def test_reconcile_leaves_a_running_reviews_slot_alone(reviews: CanopyEnv, git_pool: GitPool, agent_log: Path) -> None:
    conn = journal(reviews)
    with in_tick(conn) as tick_id:
        assert main(review(sha=head(git_pool)), runner=InlineRunner()) == 0  # claimed by this live process
        db.finish_tick(conn, tick_id, "ok", "test")
    with mock.patch.dict(os.environ, {"FAKE_OVERSEER_RESULT": "CANOPY_TICK_DONE"}):
        assert main(["tick"]) == 0
        assert [s["status"] for s in pool(Path(os.environ["FAKE_TREEHOUSE_STATE"]))] == ["leased", "available"]
        row = db.get_review_run(conn, 1)
        assert row is not None
        assert row["status"] == "running"


def test_the_state_block_shows_reviewed_prs(reviews: CanopyEnv, git_pool: GitPool, agent_log: Path) -> None:
    conn = journal(reviews)
    with reviewer_reports(FINDINGS):
        run_inline(conn, "--ticket", "PROJ-1", sha=head(git_pool))
    with mock.patch.dict(os.environ, {"FAKE_OVERSEER_RESULT": "CANOPY_TICK_DONE"}):
        assert main(["tick", "--dry-run"]) == 0
    section = state_block(agent_log)["reviews"]
    assert section["agent_prs"] is True
    assert section["query"] is None
    assert section["limits"] == {
        "max_reviews": 1,
        "max_reviews_per_day": 20,
        "max_reviews_per_pr": 3,
        "started_last_24h": 1,
    }
    assert section["running"] == []
    [reviewed] = section["prs"]
    assert (reviewed["url"], reviewed["ticket"], reviewed["review_runs"]) == (PR, "PROJ-1", 1)
    latest = reviewed["latest"]
    assert (latest["status"], latest["verdict"], latest["impact"]) == ("done", "findings", "normal")
    assert latest["findings"] == ["retry never stops"]
    assert latest["reviewed_at"] == f"{latest['ended_at'][:19]}Z"
    # The overseer passes it as the unit's review cursor, which takes whole seconds only.
    with in_tick(conn):
        assert main(["ticket", "set", "PROJ-1", "--repo", "repo", "--cursor", f"review={latest['reviewed_at']}"]) == 0
        assert "comment" not in latest


def test_attention_about_a_pr_without_a_ticket(
    reviews: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    commands = [
        ["canopy", "attention", "--pr", PR, "review_failed", "--detail", "review run 3 ended crashed"],
        ["canopy", "attention", "PROJ-1", "review_limit", "--pr", f"{PR}0", "--detail", "3 of 3 reviews"],
    ]
    with mock.patch.dict(
        os.environ, {"FAKE_OVERSEER_COMMANDS": json.dumps(commands), "FAKE_OVERSEER_RESULT": "CANOPY_TICK_DONE"}
    ):
        assert main(["tick"]) == 0
        conn = journal(reviews)
        assert [(i.subject, i.reason, i.detail) for i in attention.current(conn)] == [
            ("PROJ-1", "review_limit", f"3 of 3 reviews; allow it another review with `canopy grant {PR}0 review`"),
            (f"pr:{PR}", "review_failed", "review run 3 ended crashed"),
        ]
        capsys.readouterr()
        assert main(["decisions"]) == 0
        assert f"pr:{PR}  attention:review_failed" in capsys.readouterr().out
        with in_tick(conn) as tick_id:
            assert main(["attention", "review_failed", "--detail", "x"]) == 2
            assert main(["attention", "--pr", "http://plain", "review_failed", "--detail", "x"]) == 2
            assert decisions(conn, tick_id) == []


def test_review_wait_records_a_plain_pr_url_and_refuses_anything_else(
    reviews: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = reviews.journal()
    with in_tick(conn) as tick_id:
        for bad in ("http://x.test/pull/1", "javascript:alert(1)", f"{PR}/{'x' * 300}"):
            assert main(["review", "wait", "--pr", bad, "--rationale", "draft"]) == 2
            assert "must be a plain https:// URL" in capsys.readouterr().err
        assert decisions(conn, tick_id) == []
        assert main(["review", "wait", "--pr", PR, "--rationale", "draft"]) == 0
        assert decisions(conn, tick_id) == [(None, PR, "wait", "draft")]


def test_a_sink_that_takes_reviews_hears_when_one_ends(
    reviews: CanopyEnv, git_pool: GitPool, agent_log: Path, tmp_path: Path
) -> None:
    out = tmp_path / "sink.txt"
    script = tmp_path / "sink"
    script.write_text('#!/bin/sh\ncat >> "$1"\necho "--" >> "$1"\n')
    script.chmod(0o755)
    reviews.write_user(
        reviews.user_file.read_text()
        + f"\n[notify.sinks.s]\ncmd = '{script} {out}'\nformat = 'text'\nevents = ['reviews']\n"
    )
    with mock.patch.dict(os.environ, {"FAKE_OVERSEER_RESULT": "CANOPY_TICK_DONE"}):
        assert main(["tick"]) == 0
        conn = journal(reviews)
        with reviewer_reports(FINDINGS):
            run_inline(conn, "--ticket", "PROJ-1", sha=head(git_pool))
            assert main(["tick"]) == 0
            [message] = out.read_text().split("--\n")[:-1]
            assert f"< review run 1 of {PR} (PROJ-1) ended done: findings normal (1 findings)\n" in message


def test_a_reviewer_prompt_that_does_not_render_costs_the_pr_nothing(reviews: CanopyEnv, git_pool: GitPool) -> None:
    overrides = reviews.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "reviewer.md").write_text("Review {{PR_URL}}\n")
    conn = journal(reviews)
    with in_tick(conn) as tick_id:
        assert main(review(sha=head(git_pool)), runner=InlineRunner()) == 1
        [(_, _, action, reason)] = decisions(conn, tick_id)
        assert action == "refused:bad_prompt"
        assert reason.endswith("missing required placeholder {{SHA}}, {{CHECKOUT}}")
        assert conn.execute("SELECT count(*) FROM review_runs").fetchone()[0] == 0
        assert [s["status"] for s in pool(Path(os.environ["FAKE_TREEHOUSE_STATE"]))] == ["available", "available"]


def test_a_review_run_records_what_it_cost(reviews: CanopyEnv, git_pool: GitPool) -> None:
    """With OpenCode's JSON events, as the default `review_cmd` asks for, a review run records its session and cost."""
    text = reviews.user_file.read_text()
    reviews.write_user(
        text.replace("--agent canopy-reviewer {prompt}", "--agent canopy-reviewer --format json {prompt}")
    )
    with reviewer_reports(FINDINGS), mock.patch.dict(os.environ, {"FAKE_REVIEWER_SESSION": "ses_review"}):
        conn = journal(reviews)
        run_id = run_inline(conn, sha=head(git_pool))
    row = db.get_review_run(conn, run_id)
    assert row is not None
    assert row["status"] == "done", Path(row["log_path"]).read_text()  # the result line is read from the text events
    assert row["session_id"] == "ses_review"
    usage = db.usage_of(row)
    assert usage is not None
    assert usage.cost_usd == 0.25  # two model calls at 0.125
    assert db.spent_since(conn, "2000-01-01T00:00:00Z") == 0.25


def test_a_timed_out_review_records_what_it_reported_before_the_kill(reviews: CanopyEnv, git_pool: GitPool) -> None:
    tokens = {"input": 1, "output": 2, "reasoning": 0, "cache": {"read": 3, "write": 4}}
    events = [
        {"type": "step_finish", "sessionID": "ses_slow", "part": {"cost": 0.5, "tokens": tokens}},
        {"type": "text", "sessionID": "ses_slow", "part": {"type": "text", "text": "still reading"}},
    ]
    stdout = "".join(json.dumps(e) + "\n" for e in events)
    conn = journal(reviews)
    runner = InlineRunner(timeout_agent=True, timeout_stdout=stdout)
    run_id = run_inline(conn, sha=head(git_pool), runner=runner)
    row = db.get_review_run(conn, run_id)
    assert row is not None
    assert row["status"] == "timeout"
    assert (row["session_id"], row["cost_usd"], row["tokens_cache_write"]) == ("ses_slow", 0.5, 4)


def test_the_default_review_cmd_asks_for_events(canopy_env: CanopyEnv) -> None:
    assert "--format json" in load(canopy_env.root, canopy_env.user_file).runtime.review_cmd


def implemented(conn: sqlite3.Connection) -> None:
    """Give PROJ-1 a branch, as its first implement would, so a resume has something to continue."""
    with worker_does(*commit_and_push("agent/PROJ-1-work")), in_tick(conn) as tick_id:
        command = ["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"]
        assert main(command, runner=InlineRunner()) == 0
        db.finish_tick(conn, tick_id, "ok", "test")
        assert main(["_run", "1"], runner=InlineRunner()) == 0


def resume(*args: str) -> list[str]:
    return ["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "resume", *args]


def test_a_resume_for_a_review_carries_its_findings_from_the_journal(
    reviews: CanopyEnv, git_pool: GitPool, agent_log: Path
) -> None:
    """Nothing of a review is on the PR (D114): the worker reads its findings in its prompt."""
    conn = journal(reviews)
    with reviewer_reports(FINDINGS):
        sha = head(git_pool)
        review_id = run_inline(conn, "--ticket", "PROJ-1", sha=sha)
    implemented(conn)
    with in_tick(conn) as tick_id:
        assert (
            main(resume("--review-run", str(review_id), "--context", "Address review run 1"), runner=InlineRunner())
            == 0
        )
        [(_, _, action, rationale)] = decisions(conn, tick_id)
        assert action == "dispatch:resume"
        assert rationale.endswith(f"; review run {review_id}")
    prompt = (reviews.state_dir / "runs" / "2.prompt").read_text()
    section = prompt.split("## canopy's review\n\n", 1)[1].split("\n\nThese findings", 1)[0]
    assert section == (
        f"canopy's review run {review_id} of {PR} at commit `{sha}` found these (verdict findings, impact normal). "
        "They are in canopy's journal only, not on the PR:\n"
        "1. **blocking** `src/retry.py:42`: retry never stops\n"
        "   > The loop resets attempts on every error.\n"
        "   > A failing call retries forever."
    )


def test_a_resume_without_a_review_says_so(reviews: CanopyEnv, git_pool: GitPool, agent_log: Path) -> None:
    conn = journal(reviews)
    implemented(conn)
    with in_tick(conn):
        assert main(resume(), runner=InlineRunner()) == 0
        assert "## canopy's review\n\nNone.\n" in (reviews.state_dir / "runs" / "2.prompt").read_text()


def test_a_review_run_goes_only_to_a_resume_of_its_own_ticket(
    reviews: CanopyEnv, git_pool: GitPool, agent_log: Path
) -> None:
    conn = journal(reviews)
    sha = head(git_pool)
    with reviewer_reports(FINDINGS):
        of_ticket = run_inline(conn, "--ticket", "PROJ-1", sha=sha)
        of_query = run_inline(conn, sha=sha, pr=f"{PR}0")
        # A commit origin does not have: the run fails, with nothing for a worker.
        failed = run_inline(conn, "--ticket", "PROJ-1", sha="b" * 40)
    implemented(conn)
    with in_tick(conn) as tick_id:
        for args in (
            resume("--review-run", "99"),
            resume("--review-run", str(of_query)),
            resume("--review-run", str(failed)),
            [*resume()[:-2], "--kind", "fix-ci", "--review-run", str(of_ticket)],
        ):
            assert main(args, runner=InlineRunner()) == 1
        assert [(d[2], d[3]) for d in decisions(conn, tick_id)] == [
            ("refused:bad_review", "there is no review run 99"),
            ("refused:bad_review", f"review run {of_query} reviewed {PR}0, not a PR of PROJ-1"),
            ("refused:bad_review", f"review run {failed} ended failed with no findings to address"),
            ("refused:bad_review", "--review-run names findings for a resume to address; it is for resume only"),
        ]


def test_the_operator_reads_reviews_in_canopy(
    reviews: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = journal(reviews)
    assert main(["review", "show"]) == 0
    assert capsys.readouterr().out == "no reviews in the last 14 days\n"
    with reviewer_reports({**FINDINGS, "summary": "One blocking defect.\x1b[2J"}):
        sha = head(git_pool)
        run_id = run_inline(conn, "--ticket", "PROJ-1", sha=sha)
    capsys.readouterr()
    assert main(["review", "show"]) == 0
    [line] = capsys.readouterr().out.splitlines()
    assert line.startswith(f"{run_id}  ")
    assert line.endswith(f"  done  findings, 1 findings, impact normal  {PR} @ {sha[:7]}")
    assert main(["review", "show", str(run_id)]) == 0
    shown = capsys.readouterr().out
    assert shown.startswith(f"review run {run_id} of {PR} (PROJ-1) at {sha}\ndone, started ")
    assert "\x1b" not in shown
    assert "verdict findings, impact normal\n\nOne blocking defect. [2J\n\n1. **blocking** `src/retry.py:42`" in shown
    assert main(["review", "show", "99"]) == 1


def feature_commit(git_pool: GitPool, tmp_path: Path) -> str:
    """Push a commit adding `retry.py` on a branch `feature` off origin's `main`, and return it."""
    seed = tmp_path / "seed"
    git("checkout", "--quiet", "-b", "feature", cwd=seed)
    (seed / "retry.py").write_text("while True:\n    call()\n")
    git("add", "retry.py", cwd=seed)
    git("commit", "--quiet", "-m", "retry", cwd=seed)
    git("push", "--quiet", str(git_pool.origin), "feature", cwd=seed)
    sha = git_pool.remote_head("feature")
    assert sha is not None
    return sha


def test_a_review_keeps_its_commits_diff_for_the_web_ui(
    reviews: CanopyEnv, git_pool: GitPool, agent_log: Path, tmp_path: Path
) -> None:
    """The diff against where the commit leaves the pool's base branch, beside the run's log (DESIGN §21)."""
    sha = feature_commit(git_pool, tmp_path)
    conn = journal(reviews)
    with reviewer_reports(FINDINGS):
        run_id = run_inline(conn, sha=sha)
        row = db.get_review_run(conn, run_id)
        assert row is not None
        assert (row["status"], row["base_branch"]) == ("done", "main")
        path = review_diff.path_for(row["log_path"])
        assert path.stat().st_mode & 0o777 == 0o600
        diff = review_diff.read(path)
        assert diff is not None
        [changed] = diff.files
        assert changed.path == "retry.py"
        assert [(ln.kind, ln.new, ln.text) for ln in changed.hunks[0].lines] == [
            ("add", 1, "while True:"),
            ("add", 2, "    call()"),
        ]


def test_a_review_without_its_base_branch_still_runs(
    reviews: CanopyEnv, git_pool: GitPool, agent_log: Path, tmp_path: Path
) -> None:
    """The diff is for the page only: a base origin no longer has leaves the review as it was, without one."""
    sha = feature_commit(git_pool, tmp_path)
    git("update-ref", "-d", "refs/heads/main", cwd=git_pool.origin)
    conn = journal(reviews)
    with reviewer_reports(FINDINGS):
        run_id = run_inline(conn, sha=sha)
        row = db.get_review_run(conn, run_id)
        assert row is not None
        assert row["status"] == "done", Path(row["log_path"]).read_text()
        assert not review_diff.path_for(row["log_path"]).exists()


TWO_FINDINGS = {
    **FINDINGS,
    "findings": [
        *FINDINGS["findings"],
        {"severity": "minor", "title": "log line is noisy", "location": "src/retry.py:7", "detail": "It logs twice."},
    ],
}


def test_a_dismissed_finding_reaches_no_worker_and_no_tick(
    reviews: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = journal(reviews)
    with reviewer_reports(TWO_FINDINGS):
        review_id = run_inline(conn, "--ticket", "PROJ-1", sha=head(git_pool))
    ref = f"review:{review_id}"

    # Only the operator dismisses, and only a finding the review has.
    with mock.patch.dict(os.environ, {"CANOPY_TICK_ID": "1"}):
        assert main(["dismiss", ref, "2"]) == 1
        assert "dismiss refused (inside_run)" in capsys.readouterr().err
    for args, guard in [
        ([ref, "3"], "unknown"),
        ([ref, "0"], "bad_finding"),
        ([ref, "two"], "bad_finding"),
        (["review:99", "1"], "unknown"),
        (["review:x", "1"], "bad_ref"),
        ([ref, "2", "--undo"], "unknown"),
    ]:
        assert main(["dismiss", *args]) == 1
        assert f"dismiss refused ({guard})" in capsys.readouterr().err

    assert main(["dismiss", ref, "2"]) == 0
    assert f"{ref} finding 2 is dismissed: no worker or tick acts on it." in capsys.readouterr().out
    assert main(["review", "show", str(review_id)]) == 0
    assert "2. **minor** `src/retry.py:7`: log line is noisy (dismissed)" in capsys.readouterr().out
    assert main(["review", "show"]) == 0
    assert "findings, 2 findings (1 dismissed), impact normal" in capsys.readouterr().out

    # The overseer reads only the findings the operator kept.
    with mock.patch.dict(os.environ, {"FAKE_OVERSEER_RESULT": "CANOPY_TICK_DONE"}):
        assert main(["tick", "--dry-run"]) == 0
        latest = state_block(agent_log)["reviews"]["prs"][0]["latest"]
        assert (latest["findings"], latest["dismissed_findings"]) == (["retry never stops"], 1)

        # A resume hands the worker the kept one, under its own number.
        implemented(conn)
        with in_tick(conn):
            assert main(resume("--review-run", str(review_id)), runner=InlineRunner()) == 0
            prompt = (reviews.state_dir / "runs" / "2.prompt").read_text()
            assert "1. **blocking** `src/retry.py:42`: retry never stops" in prompt
            assert "log line is noisy" not in prompt

        # With every finding dismissed, there is nothing for a worker to address.
        assert main(["dismiss", ref, "1"]) == 0
        with in_tick(conn) as tick_id:
            assert main(resume("--review-run", str(review_id)), runner=InlineRunner()) == 1
            assert [(d[2], d[3]) for d in decisions(conn, tick_id)] == [
                (
                    "refused:bad_review",
                    f"the operator dismissed every finding of review run {review_id}: none is left to address",
                )
            ]

        # Undo hands it back.
        capsys.readouterr()
        assert main(["dismiss", ref, "1", "--undo"]) == 0
        assert "is no longer dismissed: a resume hands it to the worker again." in capsys.readouterr().out
        assert db.review_dismissals(conn, review_id) == frozenset({2})


def test_findings_sent_to_a_worker_reach_its_ticket_as_the_operators_go_ahead(
    reviews: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`canopy send review:ID N` replies on the review's ticket, naming findings by number only (DESIGN §21).

    Only for a review of one of the loop's own PRs: its ticket's unit opened the PR.
    """
    conn = journal(reviews)
    sha = head(git_pool)
    with reviewer_reports(TWO_FINDINGS):
        review_id = run_inline(conn, "--ticket", "PROJ-1", sha=sha)
        query_id = run_inline(conn, sha=sha, pr="https://github.com/acme/api/pull/9")
    ref = f"review:{review_id}"
    implemented(conn)

    with mock.patch.dict(os.environ, {"CANOPY_RUN_ID": "1"}):
        assert main(["send", ref, "1"]) == 1
        assert "send refused (inside_run)" in capsys.readouterr().err
    assert main(["dismiss", ref, "2"]) == 0
    for args, guard in [
        ([ref, "3"], "unknown"),
        ([ref, "0"], "bad_finding"),
        ([ref, "2"], "dismissed"),
        (["review:99", "1"], "unknown"),
        # A PR review.query matched; and PROJ-1's own review, now that its unit has the PR its implement's worker
        # reported instead, as after a `canopy forget` and a new PR: no worker pushes to the reviewed one any more.
        ([f"review:{query_id}", "1"], "not_ours"),
        ([ref, "1"], "not_ours"),
        (["PROJ-1", "1"], "unsupported"),
    ]:
        assert main(["send", *args]) == 1
        assert f"send refused ({guard})" in capsys.readouterr().err
    # Back on the PR the review read, its findings go to PROJ-1's worker.
    db.set_unit(conn, "PROJ-1", str(reviews.root), "repo", pr_url=PR)
    assert main(["dismiss", ref, "2", "--undo"]) == 0
    capsys.readouterr()

    assert main(["send", ref, "1"]) == 0
    out = capsys.readouterr().out
    assert f"{ref} findings 1 went to PROJ-1 as message" in out
    [message] = conversation.operator_messages_after(conn, "PROJ-1", 0)
    body = f"Address finding 1 of canopy's review run {review_id}, of commit {sha[:12]}. Leave its finding 2 alone."
    assert (message["body"], message["channel"]) == (body, "cli")
    # The reviewer's words stay data: the operator's message names the finding and never quotes it.
    assert "retry never stops" not in message["body"]
    # The same command again records nothing new.
    assert main(["send", ref, "1"]) == 0
    assert "already went to PROJ-1" in capsys.readouterr().out

    # The next tick reads it as the operator's go-ahead, and a resume for the review hears both.
    with mock.patch.dict(os.environ, {"FAKE_OVERSEER_RESULT": "CANOPY_TICK_DONE"}):
        assert main(["tick", "--dry-run"]) == 0
    tickets = {t["key"]: t for t in state_block(agent_log)["tickets"]}
    assert [m["body"] for m in tickets["PROJ-1"]["operator"]["new_operator_messages"]] == [body]
    with in_tick(conn):
        command = resume("--review-run", str(review_id), "--cursor", f"message={message['id']}")
        assert main(command, runner=InlineRunner()) == 0
    prompt = (reviews.state_dir / "runs" / "2.prompt").read_text()
    assert body in prompt
    assert "1. **blocking** `src/retry.py:42`: retry never stops" in prompt


def test_a_review_names_a_ticket_only_for_the_pr_its_unit_opened(
    reviews: CanopyEnv, git_pool: GitPool, agent_log: Path
) -> None:
    """A review's purpose is settled as it starts: `own` only for its ticket's unit's PR, else `query` (DESIGN §21)."""
    conn = journal(reviews)
    other = "https://github.com/acme/api/pull/8"
    with in_tick(conn) as tick_id:
        assert main(review("--ticket", "PROJ-1", sha=head(git_pool), pr=other)) == 1
        assert main(review("--ticket", "PROJ-2", sha=head(git_pool))) == 1
        assert [(d[2], d[3]) for d in decisions(conn, tick_id)] == [
            ("refused:not_ours", f"PROJ-1's unit in repo did not open {other}; --ticket is only for the loop's own PR"),
            ("refused:not_ours", f"PROJ-2's unit in repo did not open {PR}; --ticket is only for the loop's own PR"),
        ]
    with reviewer_reports(FINDINGS):
        own = run_inline(conn, "--ticket", "PROJ-1", sha=head(git_pool))
        query = run_inline(conn, sha=head(git_pool), pr=other)
    purposes = {r["id"]: r["purpose"] for r in conn.execute("SELECT id, purpose FROM review_runs")}
    assert purposes == {own: "own", query: "query"}
