"""A run: each case's PR opened in the repository, one at a time, waited on until its review is done, then taken down.

One at a time, and every branch deleted once its review is read, so no case's PR can read another's future: a later
case's branches hold the fixes of an earlier one. Each review is saved as it ends, so a run stopped halfway keeps what
it did, and `score` reads it.
"""

from __future__ import annotations

import json
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from canopy_review_bench import commits
from canopy_review_bench.bench import BenchError, Case, Loaded
from canopy_review_bench.score import REVIEWS_FILE, RUN_FILE, Review, SpotRecord

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from canopy_review_bench.bench import Settings
    from canopy_review_bench.github import Comment, GitHub

#: Where runs are saved, under the bench file's directory.
RESULTS_DIR = "results"
_SLUG = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Clock:
    """How a run tells the time and waits: the real ones, but in tests."""

    now: Callable[[], float] = field(default=time.monotonic)
    sleep: Callable[[float], None] = field(default=time.sleep)


@dataclass(frozen=True)
class Plan:
    """What a run does."""

    cases: Sequence[Case]
    overlay: commits.Overlay
    #: The overlay's directory, as given, to record; None for no overlay.
    overlay_dir: Path | None
    #: How many times each case is reviewed, each on a PR of its own.
    repeats: int
    #: What the run is called in its results, such as the reviewer's version.
    label: str


def run(bench: Loaded, plan: Plan, github: GitHub, *, said: Callable[[str], None], clock: Clock) -> Path:
    """Review each case of `plan`, `plan.repeats` times, in the repository, saving each review as it ends.

    `said` is told what the run is doing, a line at a time.

    Returns:
        The directory the run was saved to.
    """
    settings = bench.file.bench
    started = datetime.now(UTC)
    where = _results_dir(bench.root, started)
    meta = {
        "started_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "label": plan.label,
        "repo": settings.repo,
        "host": settings.host,
        "reviewers": list(settings.reviewers),
        "tolerance": settings.tolerance,
        "overlay": str(plan.overlay_dir) if plan.overlay_dir is not None else None,
        "overlay_digest": plan.overlay.digest if not plan.overlay.empty else None,
        "overlay_files": sorted(plan.overlay.files),
        "strip": list(plan.overlay.removed),
        "draft": settings.draft,
        "cases": [c.name for c in plan.cases],
        "repeats": plan.repeats,
    }
    (where / RUN_FILE).write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    total = len(plan.cases) * plan.repeats
    n = 0
    for repeat in range(1, plan.repeats + 1):
        for case in plan.cases:
            n += 1
            said(f"case {n} of {total}: {case.name}, review {repeat} of {plan.repeats}")
            review = _review(bench, case, repeat, plan.overlay, github, said=said, clock=clock)
            with (where / REVIEWS_FILE).open("a", encoding="utf-8") as out:
                out.write(review.model_dump_json() + "\n")
            said(f"  {review.status}{f': {review.note}' if review.note else ''}")
    return where


def _results_dir(root: Path, started: datetime) -> Path:
    parent = root / RESULTS_DIR
    parent.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    for n in range(1, 100):
        where = parent / (stamp if n == 1 else f"{stamp}-{n}")
        try:
            where.mkdir()
        except FileExistsError:
            continue
        return where
    raise BenchError(f"{parent} holds too many runs started at {stamp}")


def _review(
    bench: Loaded,
    case: Case,
    repeat: int,
    overlay: commits.Overlay,
    github: GitHub,
    *,
    said: Callable[[str], None],
    clock: Clock,
) -> Review:
    """Open `case`'s PR, wait for its review, and take it down again, whatever happened.

    Returns:
        The review, `failed` with why when its PR could not be built, pushed, or opened.
    """
    settings = bench.file.bench
    record = {"case": case.name, "kind": case.kind, "split": case.split, "source": case.source, "repeat": repeat}
    try:
        built = commits.build(bench.source, case, overlay)
    except BenchError as e:
        return Review(**record, status="failed", note=str(e))
    spots = tuple(SpotRecord(path=s.path, first=s.first, last=s.last, side=s.side) for s in built.spots)
    # Branch names a team might use, with a suffix that keeps each review's apart: nothing in them names the bench.
    suffix = secrets.token_hex(3)
    slug = _SLUG.sub("-", case.title.lower()).strip("-")[:40].strip("-") or "change"
    base, head = f"main-{suffix}", f"{slug}-{suffix}"
    pr: int | None = None
    pushed = False
    failure: str | None = None
    comments: list[Comment] = []
    try:
        commits.push(bench.source, settings.url, {base: built.base, head: built.head})
        pushed = True
        pr = github.open_pr(base=base, head=head, title=case.title, body=case.body, draft=settings.draft)
        said(f"  opened PR {pr}, waiting for {', '.join(settings.reviewers)}")
        comments = _wait(github, pr, settings, clock)
    except BenchError as e:
        failure = str(e)
    finally:
        left = _take_down(github, pr, (head, base) if pushed else ())
    status = "failed" if failure is not None else "reviewed" if comments else "silent"
    note = "; ".join([*([failure] if failure is not None else []), *left])
    return Review(**record, status=status, note=note, pr=pr, spots=spots, comments=tuple(comments))


def _wait(github: GitHub, pr: int, settings: Settings, clock: Clock) -> list[Comment]:
    """Wait until the reviewer has posted and then gone quiet, or the wait is over.

    Returns:
        The reviewer's comments, none when it posted nothing in time.
    """
    reviewers = settings.reviewers
    deadline = clock.now() + settings.wait_minutes * 60
    seen: list[Comment] = []
    changed = clock.now()
    while True:
        found = [c for c in github.comments(pr) if c.author in reviewers]
        now = clock.now()
        if len(found) != len(seen):
            seen, changed = found, now
        if seen and now - changed >= settings.quiet_minutes * 60:
            return seen
        if now >= deadline:
            return seen
        clock.sleep(settings.poll_seconds)


def _take_down(github: GitHub, pr: int | None, branches: Sequence[str]) -> list[str]:
    """Close `pr`, if it was opened, and delete `branches`, trying each whatever the others did.

    Returns:
        What could not be taken down, and why.
    """
    left: list[str] = []
    if pr is not None:
        try:
            github.close(pr)
        except BenchError as e:
            left.append(f"PR {pr} not closed: {e}")
    for branch in branches:
        try:
            github.delete_branch(branch)
        except BenchError as e:
            left.append(f"branch {branch} not deleted: {e}")
    return left
