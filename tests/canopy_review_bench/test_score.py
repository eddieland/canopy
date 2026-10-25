"""Scoring a run: what finds a bug, what counts as a false alarm, and the summary's numbers."""

import pytest
from canopy_review_bench.bench import Side
from canopy_review_bench.github import Comment
from canopy_review_bench.score import Rate, Review, SpotRecord, summary

SETTINGS: dict[str, object] = {"label": "bot 2.3", "mirror": "acme/api-bench", "reviewers": ["review-bot[bot]"]}
BUG = SpotRecord(path="src/retry.py", first=5, last=6, side=Side.BASE)


def comment(path: str = "src/retry.py", line: int = 5, side: Side = Side.BASE) -> Comment:
    """Return an inline comment of the reviewer's."""
    return Comment(
        kind="inline",
        author="review-bot[bot]",
        body="b",
        at="t",
        path=path,
        first=line,
        last=line,
        side=side,
    )


def review(kind: str = "bug", *comments: Comment, status: str = "reviewed", case: str = "c") -> Review:
    """Return a review of a case."""
    return Review.model_validate(
        {
            "case": case,
            "kind": kind,
            "split": "tune",
            "source": "undo_fix",
            "repeat": 1,
            "status": status,
            "spots": [BUG] if kind == "bug" else [],
            "comments": comments,
        },
    )


@pytest.mark.parametrize(
    ("found", "near"),
    [
        (comment(line=9), True),
        (comment(line=10), False),
        (comment(line=5, side=Side.HEAD), False),
        (comment(path="src/other.py"), False),
    ],
)
def test_a_bug_is_found_by_an_inline_comment_near_it_on_its_side(found: Comment, *, near: bool) -> None:
    assert (review("bug", found).found(3) is not None) is near


def test_a_comment_on_no_lines_finds_nothing_and_is_no_false_alarm() -> None:
    summary_comment = Comment(kind="review", author="review-bot[bot]", body="Looks fine", at="t")
    assert review("bug", summary_comment).found(50) is None
    assert review("clean", summary_comment).alarms == 0


@pytest.mark.parametrize(
    ("rate", "text"),
    [(Rate(7, 10), "7 of 10 (70%, 40%-89%)"), (Rate(0, 5), "0 of 5 (0%, 0%-43%)"), (Rate(0, 0), "none scored")],
)
def test_a_rate_carries_its_wilson_interval(rate: Rate, text: str) -> None:
    assert str(rate) == text


def test_the_summary_scores_bugs_and_clean_cases_and_counts_what_it_did_not_score() -> None:
    reviews = [
        review("bug", comment(), case="found"),
        review("bug", comment(line=40), case="missed"),
        review("clean", comment(path="src/x.py"), comment(path="src/y.py"), case="noisy"),
        review("clean", status="silent", case="quiet"),
        review("bug", status="failed", case="broken"),
    ]
    text = "\n".join(summary(SETTINGS, reviews, 3))
    assert "## Review bench: bot 2.3" in text
    assert "| all | 1 of 2 (50%, 9%-91%) | 1 of 2 (50%, 9%-91%) | 1.0 |" in text
    assert "| found | bug | tune | 1 of 1 | found 1 of 1, first at `src/retry.py:5` |" in text
    assert "| missed | bug | tune | 1 of 1 | found 0 of 1 |" in text
    assert "| noisy | clean | tune | 1 of 1 | 2 false alarms in 1 reviews |" in text
    assert "| broken | bug | tune | 0 of 1 | not scored: " in text
    assert "1 reviews were silent" in text
    assert "1 reviews failed and are not scored" in text


def test_a_wider_tolerance_finds_what_a_narrow_one_missed() -> None:
    reviews = [review("bug", comment(line=12))]
    assert "| all | 0 of 1" in "\n".join(summary(SETTINGS, reviews, 3))
    assert "| all | 1 of 1" in "\n".join(summary(SETTINGS, reviews, 6))
