"""A review's draft, and publishing it (DESIGN §34, ROADMAP M43): a review of a coworker's PR, as the operator's.

A `done` review of a PR the loop does not own is the first version of a review on it; the operator edits it, each change
a new version, and publishes one version, word for word, as one comment review on the commit the review read.
"""

import json
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, override
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import db, records, review_diff, review_drafts, review_drafts_manage
from canopy.core.context import Context
from canopy.core.review_drafts import Comment
from canopy.core.vocab import ReviewDraftAuthor, ReviewDraftStatus
from canopy.infra import logs, procs
from tests.canopy.helpers import present, reads, tick_reads
from tests.canopy.review_helpers import FINDINGS, feature_commit, reviewer_reports
from tests.canopy.scenario_helpers import Scenario, reviews
from tests.conftest import CanopyEnv, GitPool

#: A coworker's PR, which the loop did not open: a `review.query` match.
THEIRS = "https://github.com/acme/api/pull/8"
#: The reviewer's report on the commit `feature_commit` pushes, which adds `retry.py`'s two lines: one finding on a line
#: of the diff, one on a file the diff does not touch.
REPORT = {
    "status": "done",
    "verdict": "findings",
    "impact": "normal",
    "summary": "Two defects.",
    "findings": [
        {"severity": "blocking", "title": "loops forever", "location": "retry.py:1", "detail": "Nothing ends it."},
        {"severity": "minor", "title": "no tests", "location": "tests/test_retry.py:3", "detail": "Add one."},
    ],
}
ON_LINE = Comment("retry.py", 1, "**blocking**: loops forever\n\nNothing ends it.", finding=1)
OFF_DIFF = "**minor** at `tests/test_retry.py:3`: no tests\n\nAdd one."


@pytest.fixture
def reviewed(reviewing: CanopyEnv, scenario: Scenario, git_pool: GitPool, tmp_path: Path) -> int:
    """A `done` review of `THEIRS` at the commit `feature_commit` pushes, which kept its diff. Returns its run's id."""
    del reviewing
    sha = feature_commit(git_pool, tmp_path)
    return scenario.review(reviews(sha, THEIRS), reviewer=reviewer_reports(REPORT)).id


def newest(scenario: Scenario, run_id: int) -> review_drafts.Version:
    return review_drafts.newest(scenario.conn, present(review_drafts.of_review(scenario.conn, run_id)).id)


def draft_of(scenario: Scenario, run_id: int) -> records.ReviewDraft:
    return present(review_drafts.of_review(scenario.conn, run_id))


def posted(state: Path) -> list[dict[str, Any]]:
    return reads(state, "post")


def github(state: Path) -> dict[str, Any]:
    found: dict[str, Any] = json.loads(state.read_text())
    return found


def test_a_done_review_of_someone_elses_pr_drafts_a_review_its_finding_off_the_diff_in_the_body(
    scenario: Scenario,
    reviewed: int,
    git_pool: GitPool,
) -> None:
    first = newest(scenario, reviewed)
    assert (first.number, first.author, first.channel) == (1, ReviewDraftAuthor.REVIEWER, None)
    assert first.body == f"Two defects.\n\n{OFF_DIFF}"
    assert first.comments == [ON_LINE]
    assert first.change == f"made from review run {reviewed}'s summary and findings"
    draft = draft_of(scenario, reviewed)
    assert (draft.status, draft.pr_url) == (ReviewDraftStatus.WAITING, THEIRS)
    shown = scenario.operator("review", "draft", str(reviewed)).out
    assert f"Version 1, hash {first.hash}: made from review run {reviewed}'s summary and findings" in shown
    assert "Comment 1, on retry.py:1 (finding 1):\n    **blocking**: loops forever\n" in shown
    assert f"canopy review publish {reviewed} {first.hash}" in shown
    # A review of one of the loop's own PRs has none: its findings go to a worker.
    own = scenario.review(reviews(feature_head(git_pool), ticket="PROJ-1"), reviewer=reviewer_reports(FINDINGS)).id
    assert review_drafts.of_review(scenario.conn, own) is None
    refused = scenario.operator("review", "draft", str(own), code=1)
    assert "no draft (no_draft)" in refused.err


def feature_head(git_pool: GitPool) -> str:
    return present(git_pool.remote_head("feature"))


def test_a_reviewers_text_canopy_would_not_keep_is_left_out_alone(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    tmp_path: Path,
) -> None:
    del reviewing
    sha = feature_commit(git_pool, tmp_path)
    hidden = {**REPORT, "findings": [{**REPORT["findings"][0], "title": "loops\u200b forever"}, REPORT["findings"][1]]}
    run_id = scenario.review(reviews(sha, THEIRS), reviewer=reviewer_reports(hidden)).id
    first = newest(scenario, run_id)
    assert first.comments == []
    assert first.body == f"Two defects.\n\n{OFF_DIFF}"
    [why] = first.refused
    assert why.startswith("finding 1: its text holds")


def test_each_edit_drop_addition_and_dismissal_is_a_new_version(scenario: Scenario, reviewed: int) -> None:
    run = str(reviewed)
    scenario.operator("review", "edit", run, "--comment", "1", "--text", "This never stops.")
    scenario.operator("review", "edit", run, "--add", "retry.py:2", "--text", "Call what?")
    scenario.operator("review", "edit", run, "--body", "--text", "Two things, mainly.")
    scenario.operator("review", "edit", run, "--drop", "2")
    scenario.operator("dismiss", f"review:{reviewed}", "1")
    scenario.operator("dismiss", f"review:{reviewed}", "1", "--undo")
    versions = review_drafts.versions(scenario.conn, draft_of(scenario, reviewed).id)
    assert [(v.number, v.author, v.channel, v.change) for v in versions] == [
        (1, ReviewDraftAuthor.REVIEWER, None, f"made from review run {reviewed}'s summary and findings"),
        (2, ReviewDraftAuthor.OPERATOR, "cli", "edited comment 1"),
        (3, ReviewDraftAuthor.OPERATOR, "cli", "added a comment on retry.py:2"),
        (4, ReviewDraftAuthor.OPERATOR, "cli", "edited the body"),
        (5, ReviewDraftAuthor.OPERATOR, "cli", "dropped comment 2"),
        (6, ReviewDraftAuthor.OPERATOR, "cli", "dismissed finding 1"),
        (7, ReviewDraftAuthor.OPERATOR, "cli", "took back the dismissal of finding 1"),
    ]
    assert versions[4].comments == [Comment("retry.py", 1, "This never stops.", finding=1)]
    assert (versions[5].body, versions[5].comments) == ("Two things, mainly.", [])
    # Taken back, the finding's own words return: the operator's edit of it went with the dismissal.
    assert versions[6].comments == [ON_LINE]
    # A finding off the diff is in the body, and goes from it with its dismissal.
    scenario.operator("review", "edit", run, "--body", "--text", f"Two defects.\n\n{OFF_DIFF}")
    scenario.operator("dismiss", f"review:{reviewed}", "2")
    assert newest(scenario, reviewed).body == "Two defects."
    scenario.operator("dismiss", f"review:{reviewed}", "2", "--undo")
    assert newest(scenario, reviewed).body == f"Two defects.\n\n{OFF_DIFF}"
    # The same words again make no version.
    before = newest(scenario, reviewed).number
    scenario.operator("review", "edit", run, "--body", "--text", f"Two defects.\n\n{OFF_DIFF}")
    assert newest(scenario, reviewed).number == before


@pytest.mark.parametrize(
    ("args", "guard"),
    [
        (["--add", "retry.py:9", "--text", "x"], "off_diff"),
        (["--add", "other.py:1", "--text", "x"], "off_diff"),
        (["--comment", "5", "--text", "x"], "unknown"),
        (["--comment", "1", "--text", "a\u202eb"], "bad_text"),
        (["--comment", "1", "--text", "ghp_" + "aB3dE6gH9jK2mN5pQ8sT1vW4yZ7bC0eF3hJ6"], "bad_text"),
    ],
)
def test_an_edit_canopy_would_not_keep_is_refused(
    scenario: Scenario,
    reviewed: int,
    args: list[str],
    guard: str,
) -> None:
    refused = scenario.operator("review", "edit", str(reviewed), *args, code=1)
    assert f"edit refused ({guard})" in refused.err
    assert newest(scenario, reviewed).number == 1


def test_publishing_posts_the_version_verbatim_as_one_comment_review_on_the_reviewed_commit(
    scenario: Scenario,
    reviewed: int,
    github_state: Path,
) -> None:
    sha = present(db.get_review_run(scenario.conn, reviewed)).sha
    scenario.operator("review", "edit", str(reviewed), "--add", "retry.py:2", "--text", "Call what?")
    version = newest(scenario, reviewed)
    out = scenario.operator("review", "publish", str(reviewed), version.hash, "--submit").out
    assert posted(github_state) == [
        {
            "pr": THEIRS,
            "commit": sha,
            "delete_pending": None,
            "body": f"Two defects.\n\n{OFF_DIFF}",
            "comments": [
                {"path": "retry.py", "line": 1, "text": ON_LINE.text},
                {"path": "retry.py", "line": 2, "text": "Call what?"},
            ],
        },
    ]
    [review] = [r for r in github(github_state)["prs"][THEIRS]["reviews"] if r["item"] == "review"]
    assert (review["state"], review["commit"], review["author"]) == ("commented", sha, "me")
    draft = draft_of(scenario, reviewed)
    assert (draft.status, draft.publish_version, draft.publish_channel) == (ReviewDraftStatus.PUBLISHED, 2, "cli")
    assert draft.published_review_id == review["id"]
    assert out == f"Published version 2 of review run {reviewed}'s draft: {draft.published_url}\n"
    ids = [c["id"] for c in json.loads(present(draft.published_comments))]
    assert len(ids) == 2
    assert all(isinstance(i, int) for i in ids)
    # A draft publishes once, and takes no edit after.
    again = scenario.operator("review", "publish", str(reviewed), version.hash, "--submit", code=1)
    assert "publish refused (published)" in again.err
    edit = scenario.operator("review", "edit", str(reviewed), "--drop", "1", code=1)
    assert "edit refused (published)" in edit.err
    assert len(posted(github_state)) == 1


def test_a_stale_version_an_agent_and_a_draft_whose_diff_is_gone_publish_nothing(
    scenario: Scenario,
    reviewed: int,
    github_state: Path,
) -> None:
    first = newest(scenario, reviewed).hash
    scenario.operator("review", "edit", str(reviewed), "--drop", "1")
    stale = scenario.operator("review", "publish", str(reviewed), first, code=1)
    assert "publish refused (stale)" in stale.err
    current = newest(scenario, reviewed).hash
    with mock.patch.dict(os.environ, {"CANOPY_RUN_ID": "review-9"}):
        assert main(["review", "publish", str(reviewed), current]) == 1
        assert main(["review", "edit", str(reviewed), "--body", "--text", "Mine now."]) == 1
    assert newest(scenario, reviewed).hash == current
    review_diff.path_for(present(db.get_review_run(scenario.conn, reviewed)).log_path).unlink()
    gone = scenario.operator("review", "publish", str(reviewed), current, code=1)
    assert "publish refused (no_diff)" in gone.err
    assert posted(github_state) == []
    assert draft_of(scenario, reviewed).status is ReviewDraftStatus.WAITING


def test_a_review_whose_pr_a_ticket_now_holds_publishes_nothing(scenario: Scenario, reviewed: int) -> None:
    db.set_unit(scenario.conn, "PROJ-2", str(scenario.env.root), "repo", pr_url=THEIRS)
    refused = scenario.operator("review", "publish", str(reviewed), newest(scenario, reviewed).hash, code=1)
    assert "publish refused (not_ours)" in refused.err


def test_a_comment_github_refuses_posts_nothing_and_the_draft_waits_again(
    scenario: Scenario,
    reviewed: int,
    github_state: Path,
) -> None:
    github_state.write_text(json.dumps({"prs": {THEIRS: {}}, "refuse_lines": ["retry.py:1"]}))
    version = newest(scenario, reviewed).hash
    failed = scenario.operator("review", "publish", str(reviewed), version, "--submit", code=1)
    assert "GitHub refused comment 1, on retry.py:1" in failed.out
    draft = draft_of(scenario, reviewed)
    assert draft.status is ReviewDraftStatus.WAITING
    assert "GitHub refused comment 1" in present(draft.why)
    assert github(github_state)["prs"][THEIRS].get("reviews", []) == []


def test_publishing_stages_by_default_and_a_read_settles_what_the_operator_did_on_github(
    scenario: Scenario,
    reviewed: int,
    github_state: Path,
    ctx: Context,
) -> None:
    version = newest(scenario, reviewed).hash
    out = scenario.operator("review", "publish", str(reviewed), version).out
    [request] = posted(github_state)
    assert request["submit"] is False
    draft = draft_of(scenario, reviewed)
    assert draft.status is ReviewDraftStatus.STAGED
    assert f"submit or delete it at {THEIRS}/files" in out
    # Still pending on GitHub: it stays staged, and blocks another post on the PR.
    tick_reads(ctx)
    assert draft_of(scenario, reviewed).status is ReviewDraftStatus.STAGED
    # The operator submits it on GitHub; the next read records it as published.
    state = github(github_state)
    for line in state["prs"][THEIRS]["reviews"]:
        if line["item"] == "review":
            line["state"] = "commented"
    github_state.write_text(json.dumps(state))
    tick_reads(ctx)
    settled = draft_of(scenario, reviewed)
    assert (settled.status, settled.why) == (ReviewDraftStatus.PUBLISHED, "submitted by you on GitHub")
    assert settled.published_review_id == draft.pending_review_id


def test_a_staged_review_deleted_on_github_is_publishable_again(
    scenario: Scenario,
    reviewed: int,
    github_state: Path,
    ctx: Context,
) -> None:
    version = newest(scenario, reviewed).hash
    scenario.operator("review", "publish", str(reviewed), version)
    state = github(github_state)
    state["prs"][THEIRS]["reviews"] = []
    github_state.write_text(json.dumps(state))
    tick_reads(ctx)
    draft = draft_of(scenario, reviewed)
    assert (draft.status, draft.why) == (ReviewDraftStatus.WAITING, "the review you staged was deleted on GitHub")
    scenario.operator("review", "publish", str(reviewed), version, "--submit")
    assert draft_of(scenario, reviewed).status is ReviewDraftStatus.PUBLISHED


@pytest.mark.parametrize(("landed", "after"), [(False, ReviewDraftStatus.WAITING), (True, ReviewDraftStatus.PUBLISHED)])
def test_a_post_of_unknown_outcome_posts_nothing_more_until_a_read_settles_it(
    scenario: Scenario,
    reviewed: int,
    github_state: Path,
    ctx: Context,
    landed: bool,  # noqa: FBT001  (a parameter of the test)
    after: ReviewDraftStatus,
) -> None:
    github_state.write_text(json.dumps({"prs": {THEIRS: {}}, "post": "unknown", "posted": landed}))
    version = newest(scenario, reviewed).hash
    out = scenario.operator("review", "publish", str(reviewed), version, "--submit", code=1).out
    assert "may have been posted" in out
    assert draft_of(scenario, reviewed).status is ReviewDraftStatus.UNCONFIRMED
    again = scenario.operator("review", "publish", str(reviewed), version, "--submit", code=1)
    assert "publish refused (unconfirmed)" in again.err
    assert len(posted(github_state)) == 1
    tick_reads(ctx)
    assert draft_of(scenario, reviewed).status is after


class Stops(procs.SubprocessRunner):
    """A runner whose post stops with `error`, once the poster has posted when `posts`, before it starts otherwise."""

    def __init__(self, error: BaseException, *, posts: bool) -> None:
        """Stop with `error`, after posting if `posts`."""
        super().__init__()
        self.error = error
        self.posts = posts

    @override
    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        timeout: float | None = None,
        on_start: Callable[[int], None] | None = None,
        on_line: Callable[[str], None] | None = None,
        stdout_to_file: bool = False,
    ) -> procs.Result:
        if self.posts:
            super().run(
                args,
                cwd=cwd,
                env=env,
                stdin=stdin,
                timeout=timeout,
                on_start=on_start,
                on_line=on_line,
                stdout_to_file=stdout_to_file,
            )
        raise self.error


def publish_stopped(scenario: Scenario, ctx: Context, run_id: int, runner: procs.Runner) -> None:
    """Publish run `run_id`'s newest version with `--submit` through `runner`, which stops it before it ends."""
    seen = newest(scenario, run_id).hash
    with pytest.raises((KeyboardInterrupt, RuntimeError)):
        review_drafts_manage.publish(
            scenario.conn,
            ctx.config,
            runner,
            run_id,
            seen,
            submit=True,
            channel="cli",
            log=logs.for_tick(None),
        )


@pytest.mark.parametrize("posts", [False, True], ids=["nothing posted", "posted"])
def test_a_publish_that_raises_waits_on_a_read_and_never_posts_twice(
    scenario: Scenario,
    reviewed: int,
    github_state: Path,
    ctx: Context,
    posts: bool,  # noqa: FBT001  (a parameter of the test)
) -> None:
    error = RuntimeError("lost") if posts else KeyboardInterrupt()
    publish_stopped(scenario, ctx, reviewed, Stops(error, posts=posts))
    draft = draft_of(scenario, reviewed)
    assert draft.status is ReviewDraftStatus.UNCONFIRMED
    # The pending review the poster printed is known even though the publish never read its outcome.
    assert (draft.pending_review_id is not None) is posts
    again = scenario.operator("review", "publish", str(reviewed), newest(scenario, reviewed).hash, "--submit", code=1)
    assert "publish refused (unconfirmed)" in again.err
    assert len(posted(github_state)) == int(posts)
    tick_reads(ctx)
    assert draft_of(scenario, reviewed).status is (ReviewDraftStatus.PUBLISHED if posts else ReviewDraftStatus.WAITING)


@pytest.mark.parametrize("posts", [False, True], ids=["nothing posted", "posted"])
def test_a_publish_whose_process_died_is_settled_by_a_read_once_its_claim_outlives_the_post(
    scenario: Scenario,
    reviewed: int,
    github_state: Path,
    ctx: Context,
    posts: bool,  # noqa: FBT001  (a parameter of the test)
) -> None:
    # Killed, the publish runs no handler of its own: its claim is all it leaves.
    with mock.patch.object(review_drafts_manage, "_lost", autospec=True):
        publish_stopped(scenario, ctx, reviewed, Stops(RuntimeError("killed"), posts=posts))
    assert draft_of(scenario, reviewed).status is ReviewDraftStatus.PUBLISHING
    version = newest(scenario, reviewed).hash
    held = scenario.operator("review", "publish", str(reviewed), version, "--submit", code=1)
    assert "publish refused (publishing)" in held.err
    # Past the post's timeout and the margin, the claim is one of unknown outcome: still refused, never posted again.
    scenario.time_passes(minutes=ctx.config.connect.vcs().timeout_minutes + review_drafts_manage.CLAIM_MARGIN_MINUTES)
    later = scenario.operator("review", "publish", str(reviewed), version, "--submit", code=1)
    assert "publish refused (unconfirmed)" in later.err
    assert len(posted(github_state)) == int(posts)
    tick_reads(ctx)
    assert draft_of(scenario, reviewed).status is (ReviewDraftStatus.PUBLISHED if posts else ReviewDraftStatus.WAITING)
