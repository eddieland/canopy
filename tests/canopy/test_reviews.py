"""Reviews (DESIGN §21, ROADMAP M11): a fresh reviewer per PR commit, guarded, in a slot it never works in."""

import json
import os
import signal
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest

from canopy.cli.main import main
from canopy.core import db
from canopy.infra import procs
from canopy.loop import attention
from canopy.reviews import result
from tests.canopy.helpers import InlineRunner, in_tick, journal, pool
from tests.conftest import CanopyEnv, GitPool, git

PR = "https://github.com/acme/api/pull/7"
COMMENT = f"{PR}#issuecomment-41"
FINDINGS = {
    "status": "done",
    "verdict": "findings",
    "impact": "normal",
    "comment": COMMENT,
    "summary": "One blocking defect.",
    "findings": [{"severity": "blocking", "title": "retry never stops", "location": "src/retry.py:42"}],
}
CLEAN = {"status": "done", "verdict": "clean", "impact": "low", "comment": COMMENT, "summary": "Nothing found."}


@pytest.fixture
def reviews(canopy_env: CanopyEnv) -> CanopyEnv:
    """Reviews on, for the loop's own PRs, with the reviewer command running the fake agent as `canopy-reviewer`."""
    template = "env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-reviewer {prompt}"
    user = canopy_env.user_file.read_text().replace("[runtime]\n", f"[runtime]\nreview_cmd = '{template}'\n", 1)
    canopy_env.write_user(user + "\n[review]\nagent_prs = true\n")
    return canopy_env


def head(git_pool: GitPool) -> str:
    return git("rev-parse", "main", cwd=git_pool.origin)


def review(*args: str, sha: str, pr: str = PR) -> list[str]:
    return ["review", "run", "--pr", pr, "--sha", sha, "--repo", "repo", *args]


def decisions(conn: sqlite3.Connection, tick_id: int) -> list[tuple[str | None, str | None, str, str]]:
    return [
        (d["ticket_key"], d["pr"], str(d["action"]), str(d["rationale"])) for d in db.decisions_for_tick(conn, tick_id)
    ]


def reviewer_reports(monkeypatch: pytest.MonkeyPatch, report: object, *commands: list[str]) -> None:
    monkeypatch.setenv("FAKE_REVIEWER_RESULT", report if isinstance(report, str) else json.dumps(report))
    monkeypatch.setenv("FAKE_REVIEWER_COMMANDS", json.dumps(list(commands)))


def run_inline(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, *args: str, sha: str) -> int:
    """Start a review in its own tick and do its `_review` in this process, as the detached one would."""
    tick_id = in_tick(conn, monkeypatch)
    assert main(review(*args, sha=sha), runner=InlineRunner()) == 0
    run_id = int(conn.execute("SELECT max(id) FROM review_runs").fetchone()[0])
    assert main(["_review", str(run_id)], runner=InlineRunner()) == 0
    db.finish_tick(conn, tick_id, "ok", "test")
    monkeypatch.delenv("CANOPY_TICK_ID", raising=False)
    return run_id


def state_block(agent_log: Path) -> dict[str, Any]:
    overseer = json.loads(agent_log.read_text().splitlines()[-1])
    state: dict[str, Any] = json.loads(overseer["argv"][3].split("```json\n", 1)[1].split("\n```", 1)[0])
    return state


def test_with_reviews_off_nothing_about_them_reaches_the_overseer(
    canopy_env: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_AGENT_RESULT", "tick complete")
    assert main(["tick", "--dry-run"]) == 0
    assert "reviews" not in state_block(agent_log)
    conn = journal(canopy_env)
    tick_id = in_tick(conn, monkeypatch)
    assert main(review(sha="a" * 40), runner=InlineRunner()) == 1
    assert [d[2] for d in decisions(conn, tick_id)] == ["refused:reviews_off"]


def test_max_reviews_zero_turns_reviews_off(
    reviews: CanopyEnv, treehouse_state: Path, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reviews.write_user(reviews.user_file.read_text() + "\n[capacity]\nmax_reviews = 0\n")
    monkeypatch.setenv("FAKE_AGENT_RESULT", "tick complete")
    assert main(["tick", "--dry-run"]) == 0
    assert "reviews" not in state_block(agent_log)


def test_a_review_runs_outside_the_checkout_at_the_commit(
    reviews: CanopyEnv, git_pool: GitPool, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M11 against the fakes: the reviewer reads the checkout at the commit through a link, and the slot goes back."""
    conn = journal(reviews)
    sha = head(git_pool)
    tick_id = in_tick(conn, monkeypatch)
    reviewer_reports(monkeypatch, FINDINGS, ["git", "-C", "checkout", "rev-parse", "HEAD"], ["pwd"])
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
    assert [s["status"] for s in pool(Path(os.environ["FAKE_TREEHOUSE_STATE"]))] == ["available", "available"]
    [(ticket, pr, action, rationale)] = decisions(conn, tick_id)
    assert (ticket, pr, action) == ("PROJ-1", PR, "dispatch:review")
    assert rationale.startswith(f"review run 1: {sha} in ")
    assert rationale.endswith("; context=Start with src/retry.py")

    prompt = reviewer["argv"][3]
    assert prompt.startswith("# canopy reviewer\n")
    assert f"- Checkout: `{run_dir / 'checkout'}` is the repository at that commit." in prompt
    assert f'<!-- canopy-review {{"v":1,"run":1,"sha":"{sha}",' in prompt
    assert "None: never report `low`." in prompt
    assert prompt.rstrip().endswith(result.CONTRACT)


@pytest.mark.parametrize(
    ("args", "sha", "reason"),
    [
        (["--pr", "http://x.test/pull/1"], "a" * 40, "--pr must be the PR's plain https:// URL"),
        ([], "abc", "--sha must be the full head commit"),
        ([], "A" * 40, "--sha must be the full head commit"),
    ],
)
def test_bad_pr(reviews: CanopyEnv, monkeypatch: pytest.MonkeyPatch, args: list[str], sha: str, reason: str) -> None:
    conn = journal(reviews)
    tick_id = in_tick(conn, monkeypatch)
    command = ["review", "run", *(args or ["--pr", PR]), "--sha", sha, "--repo", "repo"]
    assert main(command, runner=InlineRunner()) == 1
    [(_, _, action, rationale)] = decisions(conn, tick_id)
    assert action == "refused:bad_pr"
    assert rationale.startswith(reason)


def test_review_guards(reviews: CanopyEnv, git_pool: GitPool, agent_log: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reviews.write_user(reviews.user_file.read_text() + "\n[policy]\nmax_reviews_per_pr = 2\n")
    conn = journal(reviews)
    sha = head(git_pool)
    other = "b" * 40
    tick_id = in_tick(conn, monkeypatch)
    runner = InlineRunner()
    # Started, never run: it stays running.
    assert main(review(sha=sha), runner=runner) == 0
    assert main(review(sha=sha), runner=runner) == 1  # running
    assert main(review(sha=sha, pr=f"{PR}0"), runner=runner) == 1  # review_capacity: max_reviews is 1
    assert db.finish_review_run(conn, 1, "done", json.dumps(CLEAN))
    assert runner.run(
        ["treehouse", "return", "--force", str(pool(Path(os.environ["FAKE_TREEHOUSE_STATE"]))[0]["path"])]
    ).ok
    assert main(review(sha=sha), runner=runner) == 1  # reviewed
    assert main(review(sha=other), runner=runner) == 0
    assert db.finish_review_run(conn, 2, "failed", "{}")
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
        f"review run 1 already reviewed {sha[:12]} (clean, {COMMENT}); one review per commit"
    )
    assert reasons["refused:review_limit"] == "this PR has had 2 review runs and the limit is 2"


def test_a_review_waits_for_its_tickets_worker_and_counts_against_max_workers(
    reviews: CanopyEnv, git_pool: GitPool, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reviews.write_user(reviews.user_file.read_text() + "\n[capacity]\nmax_workers = 1\nmax_reviews = 2\n")
    conn = journal(reviews)
    tick_id = in_tick(conn, monkeypatch)
    runner = InlineRunner()
    dispatch = ["dispatch", "PROJ-1", "--repo", "repo", "--label", "agent-ready-tester", "--kind", "implement"]
    assert main(dispatch, runner=runner) == 0
    assert main(review("--ticket", "PROJ-1", sha=head(git_pool)), runner=runner) == 1
    assert main(review(sha=head(git_pool), pr=f"{PR}0"), runner=runner) == 1
    [(_, _, a1, r1), (_, _, a2, r2)] = decisions(conn, tick_id)[1:]
    assert (a1, r1) == ("refused:running", "a worker run for PROJ-1 is running; review its PR once it ends")
    assert (a2, r2) == ("refused:capacity", "1 of 1 workers and reviews are running")


def test_a_running_review_takes_worker_capacity(
    reviews: CanopyEnv, git_pool: GitPool, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reviews.write_user(reviews.user_file.read_text() + "\n[capacity]\nmax_workers = 1\n")
    conn = journal(reviews)
    tick_id = in_tick(conn, monkeypatch)
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


def test_a_dry_run_counts_its_reviews(reviews: CanopyEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = journal(reviews)
    tick_id = in_tick(conn, monkeypatch, dry_run=True)
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
        ({**FINDINGS, "comment": None}, "failed", "the reviewer reported done without the URL of a comment on this PR"),
        (
            {**FINDINGS, "comment": "https://github.com/acme/api/pull/8#c"},
            "failed",
            "the reviewer reported done without",
        ),
        # PR 70's comment starts with PR 7's URL, but is not on it.
        ({**FINDINGS, "comment": f"{PR}0#issuecomment-1"}, "failed", "the reviewer reported done without"),
        (CLEAN, "done", "reported low impact, but review.low_impact is not set; recorded as normal"),
        ({**CLEAN, "findings": FINDINGS["findings"]}, "unknown", "the reviewer's last line was not a valid result"),
        ({"status": "failed", "summary": "cannot read the PR"}, "failed", ""),
    ],
)
def test_the_harness_checks_what_it_can_of_a_result(
    reviews: CanopyEnv,
    git_pool: GitPool,
    agent_log: Path,
    monkeypatch: pytest.MonkeyPatch,
    report: dict[str, object],
    status: str,
    note: str,
) -> None:
    conn = journal(reviews)
    reviewer_reports(monkeypatch, report)
    run_id = run_inline(conn, monkeypatch, sha=head(git_pool))
    row = db.get_review_run(conn, run_id)
    assert row is not None
    assert row["status"] == status
    stored = json.loads(row["result_json"])
    assert stored.get("harness", "").startswith(note)
    if status == "done":
        assert stored["impact"] == "normal"


def test_links_out_of_the_checkout_are_removed_before_the_reviewer_reads_it(
    reviews: CanopyEnv, git_pool: GitPool, agent_log: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    reviewer_reports(monkeypatch, FINDINGS, ["ls", "checkout/"])
    run_id = run_inline(conn := journal(reviews), monkeypatch, sha=sha)
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
def test_the_review_phases_are_a_units(reviews: CanopyEnv, monkeypatch: pytest.MonkeyPatch, phase: str) -> None:
    conn = journal(reviews)
    in_tick(conn, monkeypatch)
    assert main(["ticket", "set", "PROJ-1", "--repo", "repo", "--phase", phase]) == 0
    [unit] = db.units(conn, "PROJ-1")
    assert unit["phase"] == phase


def test_a_commit_origin_does_not_have_fails_the_review(
    reviews: CanopyEnv, git_pool: GitPool, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PR of another repository fails here: its commit cannot be fetched from this one's origin."""
    conn = journal(reviews)
    run_id = run_inline(conn, monkeypatch, sha="d" * 40)
    row = db.get_review_run(conn, run_id)
    assert row is not None
    assert row["status"] == "failed"
    assert json.loads(row["result_json"])["harness"].startswith("git fetch failed: ")
    assert not agent_log.exists()  # the reviewer never ran
    assert [s["status"] for s in pool(Path(os.environ["FAKE_TREEHOUSE_STATE"]))] == ["available", "available"]


def test_a_killed_review_is_crashed_on_the_next_tick(
    reviews: CanopyEnv, git_pool: GitPool, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = journal(reviews)
    tick_id = in_tick(conn, monkeypatch)
    monkeypatch.setenv("FAKE_REVIEWER_SLEEP", "60")
    assert main(review(sha=head(git_pool))) == 0
    db.finish_tick(conn, tick_id, "ok", "test")
    monkeypatch.delenv("CANOPY_TICK_ID")
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

    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")
    assert main(["tick"]) == 0
    crashed = db.get_review_run(conn, 1)
    assert crashed is not None
    assert crashed["status"] == "crashed"
    while procs.alive(agent_pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not procs.alive(agent_pid)
    assert [s["status"] for s in pool(treehouse_state)] == ["available", "available"]
    assert not run_dir.exists()
    assert git_pool.slots[0].is_dir()  # removing the run's directory never follows its link


def test_reconcile_leaves_a_running_reviews_slot_alone(
    reviews: CanopyEnv, git_pool: GitPool, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = journal(reviews)
    tick_id = in_tick(conn, monkeypatch)
    assert main(review(sha=head(git_pool)), runner=InlineRunner()) == 0  # claimed by this live process
    db.finish_tick(conn, tick_id, "ok", "test")
    monkeypatch.delenv("CANOPY_TICK_ID")
    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")
    assert main(["tick"]) == 0
    assert [s["status"] for s in pool(Path(os.environ["FAKE_TREEHOUSE_STATE"]))] == ["leased", "available"]
    row = db.get_review_run(conn, 1)
    assert row is not None
    assert row["status"] == "running"


def test_the_state_block_shows_reviewed_prs(
    reviews: CanopyEnv, git_pool: GitPool, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = journal(reviews)
    reviewer_reports(monkeypatch, FINDINGS)
    run_inline(conn, monkeypatch, "--ticket", "PROJ-1", sha=head(git_pool))
    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")
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
    assert (latest["status"], latest["verdict"], latest["impact"], latest["comment"]) == (
        "done",
        "findings",
        "normal",
        COMMENT,
    )
    assert latest["findings"] == ["retry never stops"]


def test_attention_about_a_pr_without_a_ticket(
    reviews: CanopyEnv,
    treehouse_state: Path,
    agent_log: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    commands = [
        ["canopy", "attention", "--pr", PR, "review_failed", "--detail", "review run 3 ended crashed"],
        ["canopy", "attention", "PROJ-1", "review_unposted", "--pr", f"{PR}0", "--detail", "comment missing"],
    ]
    monkeypatch.setenv("FAKE_OVERSEER_COMMANDS", json.dumps(commands))
    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")
    assert main(["tick"]) == 0
    conn = journal(reviews)
    assert [(i.subject, i.reason) for i in attention.current(conn)] == [
        ("PROJ-1", "review_unposted"),
        (f"pr:{PR}", "review_failed"),
    ]
    capsys.readouterr()
    assert main(["decisions"]) == 0
    assert f"pr:{PR}  attention:review_failed" in capsys.readouterr().out
    tick_id = in_tick(conn, monkeypatch)
    assert main(["attention", "review_failed", "--detail", "x"]) == 2
    assert main(["attention", "--pr", "http://plain", "review_failed", "--detail", "x"]) == 2
    assert decisions(conn, tick_id) == []


def test_a_sink_that_takes_reviews_hears_when_one_ends(
    reviews: CanopyEnv, git_pool: GitPool, agent_log: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "sink.txt"
    script = tmp_path / "sink"
    script.write_text('#!/bin/sh\ncat >> "$1"\necho "--" >> "$1"\n')
    script.chmod(0o755)
    reviews.write_user(
        reviews.user_file.read_text()
        + f"\n[notify.sinks.s]\ncmd = '{script} {out}'\nformat = 'text'\nevents = ['reviews']\n"
    )
    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")
    assert main(["tick"]) == 0
    conn = journal(reviews)
    reviewer_reports(monkeypatch, FINDINGS)
    run_inline(conn, monkeypatch, "--ticket", "PROJ-1", sha=head(git_pool))
    monkeypatch.setenv("FAKE_OVERSEER_RESULT", "tick complete")
    assert main(["tick"]) == 0
    [message] = out.read_text().split("--\n")[:-1]
    assert f"< review run 1 of {PR} (PROJ-1) ended done: findings normal {COMMENT}\n" in message


def test_a_reviewer_prompt_that_does_not_render_costs_the_pr_nothing(
    reviews: CanopyEnv, git_pool: GitPool, monkeypatch: pytest.MonkeyPatch
) -> None:
    overrides = reviews.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "reviewer.md").write_text("Review {{PR_URL}}\n")
    conn = journal(reviews)
    tick_id = in_tick(conn, monkeypatch)
    assert main(review(sha=head(git_pool)), runner=InlineRunner()) == 1
    [(_, _, action, reason)] = decisions(conn, tick_id)
    assert action == "refused:bad_prompt"
    assert reason.endswith("missing required placeholder {{SHA}}, {{CHECKOUT}}, {{RUN_ID}}")
    assert conn.execute("SELECT count(*) FROM review_runs").fetchone()[0] == 0
    assert [s["status"] for s in pool(Path(os.environ["FAKE_TREEHOUSE_STATE"]))] == ["available", "available"]
