"""A run against a fake GitHub: each case's PR opened, waited on, taken down, and saved; and the command lines."""

import json
import operator
from pathlib import Path

import canopy_review_bench
from canopy_review_bench import bench, commits, score
from canopy_review_bench import run as run_module
from canopy_review_bench.github import GitHub

from tests.canopy_review_bench.helpers import (
    BOT,
    FakeClock,
    FakeGitHub,
    Source,
    bench_file,
    github_does,
    inline,
    said,
    source_repo,
)
from tests.conftest import git, invoke

BUG_TITLE = "Simplify fetch"
CLEAN_TITLE = "Wait between attempts"


def mirror(tmp_path: Path) -> Path:
    """Make a bare repository to push to, as the mirror's git remote."""
    path = tmp_path / "mirror.git"
    git("init", "--quiet", "--bare", str(path), cwd=tmp_path)
    return path


def cases(source: Source) -> str:
    """Return a bug case that undoes the source's fix and a clean one that replays its PR."""
    return f"""
[[cases]]
name = "zero-attempts"
kind = "bug"
title = "{BUG_TITLE}"
body = "Less code in fetch."
undo_fix = {{ fix = "{source.fix}", paths = ["src"] }}

[[cases]]
name = "retry-delay"
kind = "clean"
title = "{CLEAN_TITLE}"
replay = {{ base = "{source.base}", head = "{source.head}" }}
"""


def reviewer(title: str, poll: int) -> dict[str, list[dict[str, object]]]:
    """Review as a bot does: an inline comment beside the deleted guard, and praise for the clean PR."""
    if title == BUG_TITLE:
        return {"inline": [inline("src/retry.py", 5, side="LEFT"), inline("src/retry.py", 5, reply_to=1)]}
    return {"conversation": [said("Looks good."), said("Agreed.", login="alice")], "reviews": []}


def test_a_run_reviews_each_case_takes_its_pr_down_and_scores_it(tmp_path: Path) -> None:
    source = source_repo(tmp_path)
    remote = mirror(tmp_path)
    path = bench_file(tmp_path, cases(source), push_url=str(remote), quiet_minutes=0)
    with github_does(FakeGitHub(reviewer)) as github:
        result = invoke(canopy_review_bench.main, ["run", str(path), "--label", "bot 2.3"])
    assert result.exit_code == 0, result.output
    assert "| all | 1 of 1 (100%, 21%-100%) | 0 of 1 (0%, 0%-79%) | 0.0 |" in result.stdout
    assert "1 comments were on no lines" in result.stdout
    # Each PR was opened with the case's title and body, from branches whose names say nothing of the bench.
    opened = sorted(github.opened.values(), key=operator.itemgetter("title"))
    assert [f["title"] for f in opened] == [BUG_TITLE, CLEAN_TITLE]
    assert opened[0]["body"] == "Less code in fetch."
    assert opened[0]["head"].startswith("simplify-fetch-")
    assert opened[0]["base"].startswith("main-")
    assert github.closed == [1, 2]
    assert sorted(github.deleted) == sorted(b for f in opened for b in (f["base"], f["head"]))
    # What was pushed is the case's PR: the bug case's head undoes the fix on a base with no history.
    head = opened[0]["head"]
    assert git("log", "--format=%s", head, cwd=remote).splitlines() == [BUG_TITLE, commits.BASE_MESSAGE]
    saved = sorted((tmp_path / "results").iterdir())
    assert len(saved) == 1
    meta, reviews = score.read(saved[0])
    assert meta["label"] == "bot 2.3"
    assert [(r.case, r.status, r.pr) for r in reviews] == [
        ("zero-attempts", "reviewed", 1),
        ("retry-delay", "reviewed", 2),
    ]
    # A reply is not a finding of its own, and only the reviewer's comments are kept.
    assert len(reviews[0].comments) == 1
    assert [c.body for c in reviews[1].comments] == ["Looks good."]


def test_a_silent_reviewer_is_waited_for_until_the_wait_is_over(tmp_path: Path) -> None:
    source = source_repo(tmp_path)
    loaded = bench.load(
        bench_file(tmp_path, cases(source), push_url=str(mirror(tmp_path)), wait_minutes=2, poll_seconds=30),
    )
    clock = FakeClock()
    with github_does(FakeGitHub(lambda _title, _poll: {})) as github:
        where = run(loaded, clock, names=("retry-delay",))
    _, reviews = score.read(where)
    assert [r.status for r in reviews] == ["silent"]
    assert clock.slept == [30, 30, 30, 30]
    assert github.closed == [1]


def test_a_review_is_done_once_the_reviewer_goes_quiet(tmp_path: Path) -> None:
    source = source_repo(tmp_path)
    loaded = bench.load(bench_file(tmp_path, cases(source), push_url=str(mirror(tmp_path)), quiet_minutes=1))

    def slow(_title: str, poll: int) -> dict[str, list[dict[str, object]]]:
        return {"inline": [inline("src/a.py", n) for n in range(1, min(poll, 3) + 1)]}

    clock = FakeClock()
    with github_does(FakeGitHub(slow)):
        where = run(loaded, clock, names=("retry-delay",))
    _, reviews = score.read(where)
    assert len(reviews[0].comments) == 3
    # A comment came at the polls at 30, 60, and 90 seconds; the review is done a minute after the last.
    assert clock.at == 150


def test_a_pr_that_cannot_be_opened_fails_and_its_branches_are_deleted(tmp_path: Path) -> None:
    source = source_repo(tmp_path)
    loaded = bench.load(bench_file(tmp_path, cases(source), push_url=str(mirror(tmp_path))))
    with github_does(FakeGitHub(reviewer, fails="POST")) as github:
        where = run(loaded, FakeClock(), names=("retry-delay",))
    _, reviews = score.read(where)
    assert [(r.status, r.pr) for r in reviews] == [("failed", None)]
    assert "HTTP 422" in reviews[0].note
    assert len(github.deleted) == 2
    assert github.closed == []


def test_a_push_that_fails_opens_nothing_and_deletes_nothing(tmp_path: Path) -> None:
    source = source_repo(tmp_path)
    loaded = bench.load(bench_file(tmp_path, cases(source), push_url=str(tmp_path / "nowhere")))
    with github_does(FakeGitHub(reviewer)) as github:
        where = run(loaded, FakeClock(), names=("retry-delay",))
    _, reviews = score.read(where)
    assert reviews[0].status == "failed"
    assert "git -c core.quotePath=off exited" in reviews[0].note
    assert (github.opened, github.deleted) == ({}, [])


def test_check_shows_each_cases_pr_and_opens_nothing(tmp_path: Path) -> None:
    source = source_repo(tmp_path)
    path = bench_file(tmp_path, cases(source))
    with github_does(FakeGitHub(reviewer)) as github:
        result = invoke(canopy_review_bench.main, ["check", str(path)])
    assert result.exit_code == 0, result.output
    assert "zero-attempts  bug  undo_fix  tune" in result.stdout
    assert "bug at src/retry.py:5-6 (base)" in result.stdout
    assert "retry-delay  clean  replay  tune" in result.stdout
    assert github.opened == {}


def test_score_scores_a_saved_run_again_with_another_tolerance(tmp_path: Path) -> None:
    source = source_repo(tmp_path)
    path = bench_file(tmp_path, cases(source), push_url=str(mirror(tmp_path)), quiet_minutes=0)

    def far(title: str, _poll: int) -> dict[str, list[dict[str, object]]]:
        return {"inline": [inline("src/retry.py", 12, side="LEFT")]} if title == BUG_TITLE else {}

    with github_does(FakeGitHub(far)):
        invoke(canopy_review_bench.main, ["run", str(path), "--case", "zero-attempts"])
    (saved,) = (tmp_path / "results").iterdir()
    assert json.loads((saved / score.RUN_FILE).read_text())["reviewers"] == [BOT]
    narrow = invoke(canopy_review_bench.main, ["score", str(saved)])
    wide = invoke(canopy_review_bench.main, ["score", str(saved), "--tolerance", "6"])
    assert "| all | 0 of 1" in narrow.stdout
    assert "| all | 1 of 1" in wide.stdout


def run(loaded: bench.Loaded, clock: FakeClock, *, names: tuple[str, ...]) -> Path:
    """Run the cases `names` names, with no overlay, once each."""
    plan = run_module.Plan(bench.chosen(loaded.file.cases, names, None), commits.NO_OVERLAY, None, 1, "")
    github = GitHub(loaded.file.bench.mirror, loaded.file.bench.host)
    return run_module.run(loaded, plan, github, said=lambda _line: None, clock=clock.clock)
