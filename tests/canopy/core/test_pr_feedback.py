"""The feedback people left on PRs canopy observed (DESIGN §11): other people's, not bots', and when a PR waited."""

from canopy.core import pr_feedback, records
from canopy.core.vocab import PrState, ReviewItem, ReviewState

PR = "https://github.com/acme/web/pull/7"


def feedback(at: str | None, state: ReviewState | None = ReviewState.APPROVED) -> pr_feedback.Feedback:
    """A review made at `at` in `state`, or a comment without one."""
    item = ReviewItem.COMMENT if state is None else ReviewItem.REVIEW
    return pr_feedback.Feedback(pr_url=PR, item=item, author="dana", state=state, created_at=at)


def pr(*, ready_at: str | None, review_requested_at: str | None) -> records.ObservedPr:
    """The reader's read of `PR` with GitHub's ready and review-requested times as given."""
    return records.ObservedPr(
        url=PR,
        repository="acme/web",
        number=7,
        head_sha=None,
        base_ref=None,
        state=PrState.OPEN,
        draft=False,
        mergeable=None,
        author="op",
        observed_at="2026-10-08T12:00:00.000Z",
        labels="[]",
        mergeable_state=None,
        title=None,
        created_at=ready_at,
        ready_at=ready_at,
        review_requested_at=review_requested_at,
        merged_at=None,
        closed_at=None,
    )


def test_a_pr_waits_from_the_review_asked_for_else_from_ready() -> None:
    """A review asked for once ready starts the wait; without one, ready does; without either, nothing does."""
    asked = pr(ready_at="2026-10-08T09:00:00.000Z", review_requested_at="2026-10-08T10:00:00.000Z")
    assert pr_feedback.waiting_since(asked) == "2026-10-08T10:00:00.000Z"
    ready = pr(ready_at="2026-10-08T09:00:00.000Z", review_requested_at=None)
    assert pr_feedback.waiting_since(ready) == "2026-10-08T09:00:00.000Z"
    assert pr_feedback.waiting_since(pr(ready_at=None, review_requested_at=None)) is None


def test_the_first_review_is_the_earliest_at_or_after_the_start_and_never_a_comment() -> None:
    """A comment, a review before the start, and one with no time are passed over."""
    said = [
        feedback("2026-10-08T12:00:00.000Z"),
        feedback("2026-10-08T09:00:00.000Z"),
        feedback("2026-10-08T10:30:00.000Z", None),
        feedback(None),
        feedback("2026-10-08T11:00:00.000Z", ReviewState.CHANGES_REQUESTED),
    ]
    first = pr_feedback.first_review(said, "2026-10-08T10:00:00.000Z")
    assert first is not None
    assert (first.created_at, first.state) == ("2026-10-08T11:00:00.000Z", ReviewState.CHANGES_REQUESTED)
    assert pr_feedback.first_review(said, "2026-10-08T12:00:01.000Z") is None
