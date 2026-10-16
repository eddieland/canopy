"""Review requests (DESIGN §21, ROADMAP M42): the operator asks canopy to review a PR the loop does not own."""

import os
import sqlite3
from pathlib import Path
from unittest import mock

import httpx2
import pytest

from canopy.cli.main import main
from canopy.core import conversation, db, review_requests
from canopy.core.config import load
from canopy.core.context import Context
from canopy.infra import resources
from tests.canopy.helpers import InlineRunner, context, in_tick, operator, state_block
from tests.canopy.review_helpers import CLEAN, FINDINGS, head, review, review_decisions, reviewer_reports, run_inline
from tests.canopy.web_helpers import refused, signed_in_client
from tests.conftest import CanopyEnv, GitPool

PR = "https://github.com/acme/other/pull/12"
LOOP_PR = "https://github.com/acme/api/pull/7"


@pytest.fixture
def requests_env(canopy_env: CanopyEnv) -> CanopyEnv:
    """A reviewer command and no `[review]` table: reviews are on only while a request is open."""
    template = "env OPENCODE_CONFIG_DIR={definitions_dir} agent run --agent canopy-reviewer {prompt}"
    user = canopy_env.user_file.read_text().replace("[runtime]\n", f"[runtime]\nreview_cmd = '{template}'\n", 1)
    canopy_env.write_user(user)
    return canopy_env


@pytest.fixture
def ctx(requests_env: CanopyEnv) -> Context:
    found = context(requests_env)
    db.migrate(found.conn, resources.migrations_dir())
    return found


def requests_of(conn: sqlite3.Connection) -> list[tuple[str, str, str | None]]:
    rows = conn.execute("SELECT pr_url, channel, end_reason FROM review_requests ORDER BY id")
    return [(r["pr_url"], r["channel"], r["end_reason"]) for r in rows]


def test_a_request_is_reviewed_at_its_head_and_ends_reviewed(
    requests_env: CanopyEnv, git_pool: GitPool, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = requests_env.journal()
    # Without a request, no `[review]` table means reviews are off.
    with in_tick(conn) as tick_id:
        assert main(review(sha=head(git_pool), pr=PR), runner=InlineRunner()) == 1
        assert [d[2] for d in review_decisions(conn, tick_id)] == ["refused:reviews_off"]
        db.finish_tick(conn, tick_id, "ok", "test")

    assert operator("start", PR, "--review") == 0
    assert f"{PR} is requested for review. The next tick reviews its head, once." in capsys.readouterr().out
    assert operator("start", PR, "--review") == 0
    assert "was already requested" in capsys.readouterr().out
    assert requests_of(conn) == [(PR, "cli", None)]

    with reviewer_reports(FINDINGS):
        run_id = run_inline(conn, sha=head(git_pool), pr=PR)
    run = db.get_review_run(conn, run_id)
    assert run is not None
    assert (run.status, run.purpose, run.ticket_key) == ("done", "request", None)
    assert requests_of(conn) == [(PR, "cli", "reviewed")]
    # With the request ended, reviews are off again.
    assert not review_requests.reviews_on(conn, load(requests_env.root))

    assert operator("show", PR) == 0
    out = capsys.readouterr().out
    assert "review request: made " in out
    assert "(reviewed)" in out
    assert f"review:{run_id}" in out


def test_a_request_made_after_its_head_was_reviewed_ends_on_the_reviewed_refusal(
    requests_env: CanopyEnv, git_pool: GitPool
) -> None:
    conn = requests_env.journal()
    assert operator("start", PR, "--review") == 0
    with reviewer_reports(CLEAN):
        run_inline(conn, sha=head(git_pool), pr=PR)
    # Asked for again at a head already reviewed: no new review will end it, so the refusal that names the review does.
    assert operator("start", PR, "--review") == 0
    with in_tick(conn, dry_run=True) as tick_id:
        assert main(review(sha=head(git_pool), pr=PR), runner=InlineRunner()) == 1
        db.finish_tick(conn, tick_id, "ok", "test")
    assert requests_of(conn)[-1] == (PR, "cli", None)
    with in_tick(conn) as tick_id:
        assert main(review(sha=head(git_pool), pr=PR), runner=InlineRunner()) == 1
        assert [d[2] for d in review_decisions(conn, tick_id)] == ["refused:reviewed"]
        db.finish_tick(conn, tick_id, "ok", "test")
    assert requests_of(conn) == [(PR, "cli", "reviewed"), (PR, "cli", "reviewed")]


def test_a_failed_review_leaves_the_request_open(requests_env: CanopyEnv, git_pool: GitPool) -> None:
    conn = requests_env.journal()
    assert operator("start", PR, "--review") == 0
    with reviewer_reports({"status": "failed", "summary": "Could not read the diff."}):
        run_id = run_inline(conn, sha=head(git_pool), pr=PR)
    run = db.get_review_run(conn, run_id)
    assert run is not None
    assert run.status == "failed"
    assert requests_of(conn) == [(PR, "cli", None)]


def test_review_end_ends_a_request_whose_pr_merged_first_and_needs_a_tick(
    requests_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = requests_env.journal()
    assert operator("start", PR, "--review") == 0
    capsys.readouterr()
    assert operator("review", "end", "--pr", PR, "--reason", "closed") == 1
    assert "no tick is running" in capsys.readouterr().err
    with in_tick(conn, dry_run=True) as tick_id:
        assert main(["review", "end", "--pr", PR, "--reason", "closed"]) == 0
        assert [d[2:] for d in review_decisions(conn, tick_id)] == [("review:end", "dry run: not ended; closed")]
        db.finish_tick(conn, tick_id, "ok", "test")
    assert requests_of(conn) == [(PR, "cli", None)]
    other = f"{PR}0"
    assert operator("start", other, "--review") == 0
    with in_tick(conn) as tick_id:
        # A PR in none of the workspace's repositories cannot be reviewed here.
        assert main(["review", "end", "--pr", other, "--reason", "unknown_repo"]) == 0
        db.finish_tick(conn, tick_id, "ok", "test")
    with in_tick(conn) as tick_id:
        assert main(["review", "end", "--pr", PR, "--reason", "stopped"]) == 2
        assert main(["review", "end", "--pr", PR, "--reason", "merged"]) == 0
        assert main(["review", "end", "--pr", PR, "--reason", "merged"]) == 1
        assert "review end refused (not_requested)" in capsys.readouterr().err
        assert [d[2:] for d in review_decisions(conn, tick_id)] == [
            ("review:end", "merged"),
            ("refused:not_requested", f"{PR} has no open request"),
        ]
        db.finish_tick(conn, tick_id, "ok", "test")
    assert requests_of(conn) == [(PR, "cli", "merged"), (other, "cli", "unknown_repo")]


@pytest.mark.parametrize("variable", ["CANOPY_TICK_ID", "CANOPY_RUN_ID"])
def test_only_the_operator_requests_or_stops_a_review(
    requests_env: CanopyEnv, capsys: pytest.CaptureFixture[str], variable: str
) -> None:
    conn = requests_env.journal()
    with mock.patch.dict(os.environ, {variable: "1"}):
        assert main(["start", PR, "--review"]) == 1
        assert "start refused (inside_run)" in capsys.readouterr().err
    assert operator("start", PR, "--review") == 0
    with mock.patch.dict(os.environ, {variable: "1"}):
        assert main(["stop", PR]) == 1
        assert "stop refused (inside_run)" in capsys.readouterr().err
    assert requests_of(conn) == [(PR, "cli", None)]


def test_a_request_refuses_recording_nothing(requests_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    conn = requests_env.journal()
    db.set_unit(conn, "PROJ-1", str(requests_env.root), "repo", pr_url=LOOP_PR)
    refusals = [
        ([LOOP_PR, "--review"], "start refused (loop_pr)"),
        (["repo#12", "--review"], "start refused (bad_pr): name the PR by its plain https:// URL"),
        (["PROJ-1", "--review"], "start refused (bad_pr)"),
        (["https://github.com/acme/other/issues/3", "--review"], "start refused (bad_ref)"),
    ]
    for args, refusal in refusals:
        assert operator("start", *args) == 1
        assert refusal in capsys.readouterr().err
    # Without --review, a PR is M14's, so a missing flag never turns a review into work on someone else's branch.
    assert operator("start", PR) == 1
    assert "start refused (unsupported)" in capsys.readouterr().err
    assert operator("start", PR, "--review", "--repo", "repo") == 2
    assert operator("stop", PR) == 1
    assert f"stop refused (not_requested): {PR} has no open review request" in capsys.readouterr().err

    requests_env.write_user(requests_env.user_file.read_text() + "\n[capacity]\nmax_reviews = 0\n")
    assert operator("start", PR, "--review") == 1
    assert "start refused (reviews_off)" in capsys.readouterr().err
    assert requests_of(conn) == []
    assert db.starts(conn) == []


def test_status_lists_an_open_request_and_stop_ends_it(
    requests_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = requests_env.journal()
    assert operator("start", PR, "--review") == 0
    capsys.readouterr()
    assert operator("status") == 0
    assert f"{PR}  " in capsys.readouterr().out
    assert operator("stop", PR) == 0
    assert "review request is stopped" in capsys.readouterr().out
    assert requests_of(conn) == [(PR, "cli", "stopped")]
    assert operator("status") == 0
    assert "Review requests" not in capsys.readouterr().out


def test_the_state_block_carries_the_open_requests(requests_env: CanopyEnv, git_pool: GitPool, agent_log: Path) -> None:
    conn = requests_env.journal()
    with mock.patch.dict(os.environ, {"FAKE_OVERSEER_RESULT": "CANOPY_TICK_DONE"}):
        # No request, no query, and agent_prs off: nothing about reviews reaches the overseer.
        assert main(["tick", "--dry-run"]) == 0
        assert "reviews" not in state_block(agent_log)
        assert operator("start", PR, "--review") == 0
        with reviewer_reports({"status": "failed", "summary": "Could not read the diff."}):
            run_id = run_inline(conn, sha=head(git_pool), pr=PR)
        assert main(["tick", "--dry-run"]) == 0
    section = state_block(agent_log)["reviews"]
    assert (section["agent_prs"], section["query"]) == (False, None)
    [requested] = section["requests"]
    assert {k: requested[k] for k in ("url", "review_runs")} == {"url": PR, "review_runs": 1}
    # The overseer matches the PR's URL to a repository by the map's clone URL.
    assert [r["url"] for r in state_block(agent_log)["repositories"]] == ["https://example.test/acme/repo.git"]
    assert (requested["latest"]["run_id"], requested["latest"]["status"]) == (run_id, "failed")
    assert [p["url"] for p in section["prs"]] == [PR]


def test_the_web_channel_requests_and_stops_a_review_as_the_cli_does(ctx: Context) -> None:
    c, headers = signed_in_client(ctx)

    def start(url: str, **params: str) -> httpx2.Response:
        return c.post("/api/pull-request/start", params={"url": url, **params}, headers=headers)

    def stop(url: str) -> httpx2.Response:
        return c.post("/api/pull-request/stop", params={"url": url}, headers=headers)

    assert refused(start("PROJ-1")).startswith("bad_pr")
    assert refused(stop(PR)).startswith("not_requested")
    assert c.post("/api/pull-request/start", params={"url": PR}).status_code == 403

    made = start(PR).json()
    assert (made["already"], made["request"]["channel"], made["request"]["ended_at"]) == (False, "web", None)
    assert start(PR).json()["already"] is True
    page = c.get("/api/pull-request", params={"url": PR}).json()
    assert page["pull_request"]["review_request"]["ended_at"] is None
    assert [p["url"] for p in c.get("/api/pull-requests").json()] == [PR]

    stopped = stop(PR).json()
    assert stopped["running_review"] is None
    request = c.get("/api/pull-request", params={"url": PR}).json()["pull_request"]["review_request"]
    assert (request["end_reason"], request["ended_at"] is not None) == ("stopped", True)
    with pytest.raises(conversation.Refused, match="not_requested"):
        review_requests.stop(ctx.conn, conversation.parse_ref(PR))
