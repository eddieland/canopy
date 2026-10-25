"""Scoring a run from what it saved, so a run can be scored again with another tolerance without reviewing again.

A review of a bug case finds the bug when one of the reviewer's inline comments is within the tolerance of a line the
bug is on, on the same side of the diff. Every inline comment on a clean case is a false alarm. A comment on no lines
(a review's body, the conversation) is counted, never scored: what a summary says cannot be placed on a line. A review
that failed, so no PR was reviewed, is not scored; a silent one, the reviewer posting nothing in time, scores as a
review with no comments, and is counted apart, since a reviewer that never ran looks the same.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from canopy_review_bench.bench import BenchError, Side, Spot
from canopy_review_bench.github import Comment  # noqa: TC001 - pydantic resolves the field's type when it validates.

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

#: The file a run's reviews are appended to, one JSON object a line.
REVIEWS_FILE = "reviews.jsonl"
#: The file a run's settings are written to.
RUN_FILE = "run.json"
#: The z of a 95% interval.
_Z = 1.96


class SpotRecord(BaseModel):
    """A spot, as a review's record keeps it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    first: int
    last: int
    side: Side

    def spot(self) -> Spot:
        """Return it as a spot."""
        return Spot(self.path, self.first, self.last, self.side)


class Review(BaseModel):
    """One review of one case, as a run saves it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case: str
    kind: Literal["bug", "clean"]
    split: Literal["tune", "holdout"]
    source: Literal["replay", "undo_fix"]
    #: Which of the case's reviews this is, from 1.
    repeat: int
    #: `reviewed` when the reviewer posted, `silent` when it posted nothing in time, `failed` when no PR was reviewed.
    status: Literal["reviewed", "silent", "failed"]
    #: Why it failed, or what went wrong cleaning up.
    note: str = ""
    pr: int | None = None
    spots: tuple[SpotRecord, ...] = ()
    #: The reviewer's comments alone.
    comments: tuple[Comment, ...] = ()

    @property
    def scored(self) -> bool:
        """Whether it counts: any review but a failed one."""
        return self.status != "failed"

    def found(self, tolerance: int) -> Comment | None:
        """Return the first of its inline comments on a line its bug is on, within `tolerance`; None when none is.

        Returns:
            The comment, or None.
        """
        spots = [s.spot() for s in self.spots]
        for c in self.comments:
            if (
                c.path is not None
                and c.first is not None
                and c.last is not None
                and c.side is not None
                and any(s.near(c.path, c.first, c.last, c.side, tolerance) for s in spots)
            ):
                return c
        return None

    @property
    def alarms(self) -> int:
        """How many of its comments are on lines of the diff."""
        return sum(c.located for c in self.comments)


@dataclass(frozen=True)
class Rate:
    """How many of how many, with a 95% Wilson interval."""

    hits: int
    of: int

    @property
    def interval(self) -> tuple[float, float]:
        """The 95% Wilson score interval of the rate, from 0 to 1; the whole range when `of` is 0."""
        if self.of == 0:
            return 0.0, 1.0
        p = self.hits / self.of
        n = self.of
        denominator = 1 + _Z**2 / n
        center = (p + _Z**2 / (2 * n)) / denominator
        half = _Z * math.sqrt(p * (1 - p) / n + _Z**2 / (4 * n**2)) / denominator
        return max(0.0, center - half), min(1.0, center + half)

    def __str__(self) -> str:
        """Return the rate in words, `7 of 10 (70%, 40-89%)`."""
        if self.of == 0:
            return "none scored"
        low, high = self.interval
        return f"{self.hits} of {self.of} ({self.hits / self.of:.0%}, {low:.0%}-{high:.0%})"


def read(results: Path) -> tuple[dict[str, object], list[Review]]:
    """Read a run's settings and its reviews from its results directory.

    Returns:
        The settings, as the run wrote them, and each review saved.

    Raises:
        BenchError: a file cannot be read, or is not a run's.
    """
    try:
        settings = json.loads((results / RUN_FILE).read_text(encoding="utf-8"))
        lines = (results / REVIEWS_FILE).read_text(encoding="utf-8").splitlines()
        reviews = [Review.model_validate_json(line) for line in lines if line.strip()]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as e:
        raise BenchError(f"{results}: {e}") from e
    if not isinstance(settings, dict):
        raise BenchError(f"{results / RUN_FILE}: not a run's settings")
    return settings, reviews


def summary(settings: dict[str, object], reviews: Sequence[Review], tolerance: int) -> list[str]:
    """Return a run's score as Markdown: what it ran with, its recall and false alarms, and each case's.

    Recall and false alarms are given overall, by split, and by where the cases came from.

    Returns:
        The lines.
    """
    scored = [r for r in reviews if r.scored]
    silent = sum(r.status == "silent" for r in reviews)
    failed = len(reviews) - len(scored)
    unlocated = sum(len(r.comments) - r.alarms for r in scored)
    reviewers = ", ".join(f"`{r}`" for r in _strings(settings, "reviewers"))
    out = [
        f"## Review bench: {settings.get('label') or 'unlabelled'}, {str(settings.get('started_at', ''))[:16]}",
        "",
        (
            f"Mirror `{settings.get('mirror')}`, reviewers {reviewers}, overlay {_overlay(settings)}. "
            f"A bug is found by an inline comment within {tolerance} lines of it."
        ),
        "",
        "| Group | Recall on bug cases | Clean reviews with a false alarm | False alarms per clean review |",
        "| --- | --- | --- | --- |",
    ]
    groups: list[tuple[str, list[Review]]] = [
        ("all", scored),
        *((f"split {split}", [r for r in scored if r.split == split]) for split in ("tune", "holdout")),
        *((f"from {source}", [r for r in scored if r.source == source]) for source in ("replay", "undo_fix")),
    ]
    for name, group in groups:
        if group:
            out.append(f"| {name} | {_recall(group, tolerance)} | {_alarmed(group)} | {_per_clean(group)} |")
    out += ["", "| Case | Kind | Split | Reviews | Score |", "| --- | --- | --- | --- | --- |"]
    for case in dict.fromkeys(r.case for r in reviews):
        mine = [r for r in reviews if r.case == case]
        first = mine[0]
        out.append(
            f"| {case} | {first.kind} | {first.split} | {sum(r.scored for r in mine)} of {len(mine)} | "
            f"{_case_score(mine, tolerance)} |",
        )
    notes = [
        f"{silent} reviews were silent, scored as no comments: check the reviewer ran on them." if silent else "",
        f"{failed} reviews failed and are not scored; their notes say why." if failed else "",
        f"{unlocated} comments were on no lines (summaries, the conversation) and are not scored." if unlocated else "",
    ]
    said = [n for n in notes if n]
    return [*out, "", *said] if said else out


def _recall(reviews: Iterable[Review], tolerance: int) -> str:
    bugs = [r for r in reviews if r.kind == "bug"]
    return str(Rate(sum(r.found(tolerance) is not None for r in bugs), len(bugs)))


def _alarmed(reviews: Iterable[Review]) -> str:
    clean = [r for r in reviews if r.kind == "clean"]
    return str(Rate(sum(r.alarms > 0 for r in clean), len(clean)))


def _per_clean(reviews: Iterable[Review]) -> str:
    clean = [r for r in reviews if r.kind == "clean"]
    return f"{sum(r.alarms for r in clean) / len(clean):.1f}" if clean else "none scored"


def _case_score(reviews: Sequence[Review], tolerance: int) -> str:
    scored = [r for r in reviews if r.scored]
    if not scored:
        return "not scored: " + "; ".join(dict.fromkeys(r.note for r in reviews if r.note))
    if scored[0].kind == "bug":
        hits = [h for r in scored if (h := r.found(tolerance)) is not None]
        where = f", first at `{hits[0].path}:{hits[0].first}`" if hits else ""
        return f"found {len(hits)} of {len(scored)}{where}"
    alarms = [r.alarms for r in scored]
    return f"{sum(alarms)} false alarms in {len(scored)} reviews"


def _strings(settings: dict[str, object], key: str) -> list[str]:
    value = settings.get(key)
    return [str(v) for v in value] if isinstance(value, list) else []


def _overlay(settings: dict[str, object]) -> str:
    digest = settings.get("overlay_digest")
    return f"`{settings.get('overlay')!s}` at {str(digest)[:12]}" if settings.get("overlay") else "none"
