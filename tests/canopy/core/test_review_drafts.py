"""A review's draft, and publishing it (DESIGN §34, ROADMAP M43): a review of a coworker's PR, as the operator's.

A `done` review of a PR the loop does not own is the first version of a review on it; the operator edits it, each change
a new version, or notes what an agent's revision should change, and publishes one version, word for word, as one
comment review on the commit the review read.
"""

import json
import os
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, override
from unittest import mock

import pytest
from syrupy.assertion import SnapshotAssertion

from canopy.cli.main import main
from canopy.core import (
    config,
    db,
    records,
    review_diff,
    review_drafts,
    review_drafts_manage,
    review_result,
    review_revisions,
    review_runs,
)
from canopy.core.context import Context
from canopy.core.replies import MAX_DRAFT_CHARS, MAX_DRAFTS
from canopy.core.review_drafts import Comment
from canopy.core.vocab import ReviewDraftAuthor, ReviewDraftStatus, ReviewRunStatus
from canopy.infra import logs, procs
from canopy.reviews import view
from tests.canopy.helpers import present, reads, tick_reads
from tests.canopy.review_helpers import (
    FINDINGS,
    OFF_DIFF,
    ON_LINE,
    REPORT,
    THEIRS,
    feature_commit,
    reviewer_reports,
)
from tests.canopy.scenario_helpers import Scenario, reviews, revises
from tests.conftest import CanopyEnv, GitPool


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
    assert first.body == OFF_DIFF
    assert first.comments == [ON_LINE]
    assert first.change == f"made from review run {reviewed}'s body and findings"
    draft = draft_of(scenario, reviewed)
    assert (draft.status, draft.pr_url) == (ReviewDraftStatus.WAITING, THEIRS)
    shown = scenario.operator("review", "draft", str(reviewed)).out
    assert f"Version 1, hash {first.hash}: made from review run {reviewed}'s body and findings" in shown
    assert "Comment 1, on retry.py:1 (finding 1):\n    loops forever\n" in shown
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
    assert first.body == OFF_DIFF
    [why] = first.refused
    assert why.startswith("finding 1: its text holds")


@pytest.mark.parametrize(
    ("said", "body", "refused"),
    [
        ("Could the client's own retry do this?", f"Could the client's own retry do this?\n\n{OFF_DIFF}", []),
        # A body canopy would not keep is left out alone, the findings kept.
        ("Could\u200b the client's own retry do this?", OFF_DIFF, ["the body: its text holds"]),
    ],
)
def test_the_reviewers_body_for_the_author_leads_the_first_version_and_its_summary_stays_out(
    reviewing: CanopyEnv,
    scenario: Scenario,
    git_pool: GitPool,
    tmp_path: Path,
    said: str,
    body: str,
    refused: list[str],
) -> None:
    del reviewing
    sha = feature_commit(git_pool, tmp_path)
    first = newest(
        scenario,
        scenario.review(reviews(sha, THEIRS), reviewer=reviewer_reports({**REPORT, "body": said})).id,
    )
    assert (first.body, first.comments) == (body, [ON_LINE])
    assert [why[: len(want)] for why, want in zip(first.refused, refused, strict=True)] == refused


def test_each_edit_drop_addition_and_dismissal_is_a_new_version(scenario: Scenario, reviewed: int) -> None:
    run = str(reviewed)
    scenario.operator("review", "edit", run, "--comment", "1", "--text", "This never stops.")
    scenario.operator("review", "edit", run, "--add", "retry.py:2", "--text", "Call what?")
    scenario.operator("review", "edit", run, "--body", "--text", "Two things, mainly.")
    scenario.operator("review", "edit", run, "--drop", "2")
    scenario.operator("dismiss", f"review:{reviewed}", "1", "--reason", "wrong")
    scenario.operator("dismiss", f"review:{reviewed}", "1", "--undo")
    versions = review_drafts.versions(scenario.conn, draft_of(scenario, reviewed).id)
    assert [(v.number, v.author, v.channel, v.change) for v in versions] == [
        (1, ReviewDraftAuthor.REVIEWER, None, f"made from review run {reviewed}'s body and findings"),
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
    scenario.operator("dismiss", f"review:{reviewed}", "2", "--reason", "wrong")
    assert newest(scenario, reviewed).body == "Two defects."
    findings = present(review_result.stored(present(review_runs.get_review_run(scenario.conn, reviewed)).result_json))
    assert review_drafts.in_body(newest(scenario, reviewed).body, findings.findings) == []
    scenario.operator("dismiss", f"review:{reviewed}", "2", "--undo")
    assert newest(scenario, reviewed).body == f"Two defects.\n\n{OFF_DIFF}"
    assert review_drafts.in_body(newest(scenario, reviewed).body, findings.findings) == [2]
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
    sha = present(review_runs.get_review_run(scenario.conn, reviewed)).sha
    scenario.operator("review", "edit", str(reviewed), "--add", "retry.py:2", "--text", "Call what?")
    version = newest(scenario, reviewed)
    out = scenario.operator("review", "publish", str(reviewed), version.hash, "--submit").out
    assert posted(github_state) == [
        {
            "pr": THEIRS,
            "commit": sha,
            "delete_pending": None,
            "body": OFF_DIFF,
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
    review_diff.path_for(present(review_runs.get_review_run(scenario.conn, reviewed)).log_path).unlink()
    gone = scenario.operator("review", "publish", str(reviewed), current, code=1)
    assert "publish refused (no_diff)" in gone.err
    assert posted(github_state) == []
    assert draft_of(scenario, reviewed).status is ReviewDraftStatus.WAITING


def test_a_review_whose_pr_a_ticket_now_holds_publishes_nothing(scenario: Scenario, reviewed: int) -> None:
    db.set_unit(scenario.conn, "PROJ-2", str(scenario.env.root), "repo", pr_url=THEIRS)
    refused = scenario.operator("review", "publish", str(reviewed), newest(scenario, reviewed).hash, code=1)
    assert "publish refused (not_ours)" in refused.err


def test_a_discarded_draft_posts_nothing_and_takes_no_edit_note_or_publish(
    scenario: Scenario,
    reviewed: int,
    github_state: Path,
) -> None:
    run, version = str(reviewed), newest(scenario, reviewed).hash
    with mock.patch.dict(os.environ, {"CANOPY_RUN_ID": "review-9"}):
        assert main(["review", "discard", run]) == 1
    assert draft_of(scenario, reviewed).status is ReviewDraftStatus.WAITING
    out = scenario.operator("review", "discard", run).out
    assert out == f"Discarded review run {reviewed}'s draft of {THEIRS}; nothing was posted.\n"
    draft = draft_of(scenario, reviewed)
    assert (draft.status, draft.why) == (ReviewDraftStatus.DISCARDED, "discarded by you through cli")
    assert "discarded by you through cli" in scenario.operator("review", "draft", run).out
    for refused, verb in [
        (("review", "publish", run, version, "--submit"), "publish"),
        (("review", "edit", run, "--drop", "1"), "edit"),
        (("reply", f"review:{reviewed}", NOTE), "reply"),
        (("review", "discard", run), "discard"),
    ]:
        assert f"{verb} refused (discarded)" in scenario.operator(*refused, code=1).err
    assert posted(github_state) == []


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


#: The reviser's report on `REPORT`'s draft, as the operator's note asks: one comment on a line of the diff, and one off
#: it, which goes in the body under its location.
REVISED: Final = {
    "status": "done",
    "body": "One defect, gently put.",
    "comments": [
        {"location": "retry.py:1", "text": "This loop never ends."},
        {"location": "tests/test_retry.py:3", "text": "A test would catch it."},
    ],
}
NOTE: Final = "Say it more gently, and fold the test finding into the body."


def wanted(scenario: Scenario) -> list[dict[str, Any]]:
    """The revisions the state block asks of the overseer now, under the config as it stands."""
    cfg = config.load(scenario.env.root, scenario.env.user_file)
    section = present(view.state_section(scenario.conn, cfg, datetime.now(UTC)))
    return [dict(w) for w in section.get("revisions", [])]


def test_a_note_starts_a_revision_on_the_next_tick_whose_result_is_the_new_version(
    scenario: Scenario,
    reviewed: int,
    github_state: Path,
) -> None:
    assert wanted(scenario) == []
    noted = scenario.operator("reply", f"review:{reviewed}", NOTE).out
    assert f"on review run {reviewed}'s draft, at version 1" in noted
    assert "Your note asks for a revision" in scenario.operator("review", "draft", str(reviewed)).out
    [asked] = wanted(scenario)
    assert (asked["review_run"], asked["pr"], asked["revisions"], asked["limit"], asked["latest"]) == (
        reviewed,
        THEIRS,
        0,
        3,
        None,
    )
    # The state block names the draft, never the note's text or the draft's.
    assert NOTE not in json.dumps(asked)
    # A dry tick checks the guards and starts nothing.
    said = scenario.overseer(*revises(reviewed)[1:], dry_run=True).out
    assert said.startswith(f"dry run: recorded a revision of review run {reviewed}'s draft")
    assert review_runs.revision_runs_of(scenario.conn, draft_of(scenario, reviewed).id) == []
    revision = scenario.review(revises(reviewed), reviewer=reviewer_reports(REVISED))
    assert revision.status is ReviewRunStatus.DONE
    assert revision.prompt.startswith("# canopy reviser\n")
    assert f"> {NOTE}" in revision.prompt
    assert "The body:\n> `tests/test_retry.py:3`" in revision.prompt
    assert "Comment 1, on `retry.py:1`:\n> loops forever" in revision.prompt
    second = newest(scenario, reviewed)
    assert (second.number, second.author, second.channel) == (2, ReviewDraftAuthor.REVISER, None)
    assert second.change == f"revision run {revision.id} revised version 1 on the operator's notes"
    assert second.body == "One defect, gently put.\n\nAt `tests/test_retry.py:3`: A test would catch it."
    assert second.comments == [Comment("retry.py", 1, "This loop never ends.")]
    # The note is answered; the revision is no review of the PR, and wrote nothing to GitHub.
    assert wanted(scenario) == []
    [(action, _)] = scenario.refuses(revises(reviewed))
    assert action == "refused:no_note"
    assert [r.id for r in review_runs.review_runs_of(scenario.conn, THEIRS)] == [reviewed]
    assert posted(github_state) == []
    assert "by a revision" in scenario.operator("review", "draft", str(reviewed)).out


def test_a_note_older_than_the_newest_version_starts_nothing(scenario: Scenario, reviewed: int) -> None:
    scenario.operator("reply", f"review:{reviewed}", NOTE)
    scenario.operator("review", "edit", str(reviewed), "--body", "--text", "Mine now.")
    assert wanted(scenario) == []
    [(action, rationale)] = scenario.refuses(revises(reviewed))
    assert action == "refused:no_note"
    assert "newer than its version 2" in rationale


def test_a_draft_past_its_revisions_takes_no_note_and_no_revision_until_the_operator_grants_one(
    scenario: Scenario,
    reviewed: int,
) -> None:
    scenario.configures(policy={"max_revisions_per_draft": 1})
    scenario.operator("reply", f"review:{reviewed}", NOTE)
    failed = scenario.review(revises(reviewed), reviewer=reviewer_reports({"status": "failed", "body": "no PR"}))
    assert failed.status is ReviewRunStatus.FAILED
    # A revision that fails leaves the draft as it was, and the note still asks: the overseer sees how it ended.
    assert newest(scenario, reviewed).number == 1
    [asked] = wanted(scenario)
    assert (asked["revisions"], asked["limit"], asked["latest"]["status"]) == (1, 1, "failed")
    refused = scenario.refuses(revises(reviewed))
    assert [action for action, _ in refused] == ["refused:revision_limit", "attention:review_limit"]
    assert f"canopy grant review:{reviewed} revision" in refused[1][1]
    again = scenario.operator("reply", f"review:{reviewed}", "Once more.", code=1)
    assert "reply refused (revision_limit)" in again.err
    granted = scenario.operator("grant", f"review:{reviewed}", "revision").out
    assert "has had 1 revisions, and may now have 2" in granted
    scenario.review(revises(reviewed), reviewer=reviewer_reports(REVISED))
    assert newest(scenario, reviewed).author is ReviewDraftAuthor.REVISER


def test_a_note_and_a_grant_are_the_operators_alone(scenario: Scenario, reviewed: int) -> None:
    with mock.patch.dict(os.environ, {"CANOPY_RUN_ID": "review-9"}):
        assert main(["reply", f"review:{reviewed}", NOTE]) == 1
        assert main(["grant", f"review:{reviewed}", "revision"]) == 1
    draft_id = draft_of(scenario, reviewed).id
    assert review_revisions.pending(scenario.conn, draft_id) == []
    assert review_revisions.granted(scenario.conn, draft_id) == 0
    mismatched = scenario.operator("grant", f"review:{reviewed}", "review", code=1)
    assert "grant refused (bad_kind)" in mismatched.err


def test_while_a_revision_runs_the_draft_takes_no_note_and_no_publish_and_an_edit_outlasts_it(
    scenario: Scenario,
    reviewed: int,
    github_state: Path,
) -> None:
    scenario.operator("reply", f"review:{reviewed}", NOTE)
    revising = scenario.starts_review(revises(reviewed), reviewer=reviewer_reports(REVISED))
    # One review run of a PR at a time: no second revision while it runs.
    [(action, _)] = scenario.refuses(revises(reviewed))
    assert action == "refused:running"
    version = newest(scenario, reviewed).hash
    held = scenario.operator("review", "publish", str(reviewed), version, "--submit", code=1)
    assert "publish refused (revising)" in held.err
    noted = scenario.operator("reply", f"review:{reviewed}", "And shorter.", code=1)
    assert "reply refused (revising)" in noted.err
    discarded = scenario.operator("review", "discard", str(reviewed), code=1)
    assert "discard refused (revising)" in discarded.err
    # The operator edits meanwhile: their version stands, and the revision's, made from the one before, is left out.
    scenario.operator("review", "edit", str(reviewed), "--body", "--text", "Mine now.")
    done = revising.finishes()
    assert done.status is ReviewRunStatus.DONE
    assert "moved on to version 2" in str(json.loads(present(done.row.result_json))["harness"])
    current = newest(scenario, reviewed)
    assert (current.number, current.author, current.body) == (2, ReviewDraftAuthor.OPERATOR, "Mine now.")
    assert posted(github_state) == []


def test_a_revision_is_held_by_the_review_guards(scenario: Scenario, reviewed: int, git_pool: GitPool) -> None:
    scenario.operator("reply", f"review:{reviewed}", NOTE)
    scenario.configures(capacity={"max_reviews": 0})
    [(action, _)] = scenario.refuses(revises(reviewed))
    assert action == "refused:reviews_off"
    scenario.configures(capacity={"max_reviews": 1, "max_reviews_per_day": 1})
    [(action, _)] = scenario.refuses(revises(reviewed))
    assert action == "refused:daily_limit"
    scenario.configures(capacity={"max_reviews_per_day": 20})
    # A review of one of the loop's own PRs has no draft to revise.
    own = scenario.review(reviews(feature_head(git_pool), ticket="PROJ-1"), reviewer=reviewer_reports(FINDINGS)).id
    [(action, _)] = scenario.refuses(revises(own))
    assert action == "refused:no_draft"


def test_a_revisions_bounds_are_a_drafts() -> None:
    assert (review_result.MAX_REVISED_TEXT, review_result.MAX_REVISED_COMMENTS) == (MAX_DRAFT_CHARS, MAX_DRAFTS)


def test_the_reviser_prompt(
    scenario: Scenario,
    reviewed: int,
    reviewing: CanopyEnv,
    markdown_snapshot: SnapshotAssertion,
) -> None:
    """The reviser's prompt, whole, so a change to its wording or to what fills it in is a diff in review."""
    scenario.operator("reply", f"review:{reviewed}", NOTE)
    revision = scenario.review(revises(reviewed), reviewer=reviewer_reports(REVISED))
    # The commit's sha changes with the time it was made.
    prompt = revision.prompt.replace(str(reviewing.state_dir), "/state").replace(revision.row.sha, "<sha>")
    assert prompt == markdown_snapshot
