"""The bench file: what it accepts, what it refuses, and how cases are chosen."""

from pathlib import Path

import pytest
from canopy_review_bench import bench
from canopy_review_bench.bench import BenchError, Side, Spot

from tests.canopy_review_bench.helpers import bench_file

SHA = "a" * 40
OTHER = "b" * 40


def test_a_bench_file_with_each_kind_of_case_loads(tmp_path: Path) -> None:
    path = bench_file(
        tmp_path,
        f"""
[[cases]]
name = "retry-delay"
kind = "bug"
title = "Wait between attempts"
replay = {{ base = "{SHA}", head = "{OTHER}" }}
lines = ["src/retry.py:11"]
base_lines = ["src/retry.py:4-5"]

[[cases]]
name = "zero-attempts"
kind = "bug"
split = "holdout"
title = "Simplify fetch"
undo_fix = {{ fix = "{SHA}", paths = ["src"] }}

[[cases]]
name = "docs"
kind = "clean"
title = "Explain fetch"
replay = {{ base = "{SHA}", head = "{OTHER}" }}
""",
        tolerance=5,
    )
    loaded = bench.load(path)
    replayed, undone, clean = loaded.file.cases
    assert loaded.source == (tmp_path / "source").resolve()
    assert loaded.file.bench.tolerance == 5
    assert loaded.file.bench.url == "https://github.com/acme/api-bench.git"
    assert replayed.spots == (Spot("src/retry.py", 11, 11, Side.HEAD), Spot("src/retry.py", 4, 5, Side.BASE))
    assert (replayed.source, undone.source, clean.source) == ("replay", "undo_fix", "replay")
    assert undone.spots == ()
    assert undone.split == "holdout"


@pytest.mark.parametrize(
    ("case", "refusal"),
    [
        (
            f'replay = {{ base = "{SHA}", head = "{OTHER}" }}\nundo_fix = {{ fix = "{SHA}" }}',
            "one of replay or undo_fix",
        ),
        ("", "one of replay or undo_fix"),
        (f'replay = {{ base = "{SHA}", head = "{OTHER}" }}', "needs lines or base_lines"),
        (f'replay = {{ base = "{SHA}", head = "abc" }}\nlines = ["a.py:1"]', "must be a full commit"),
        (f'undo_fix = {{ fix = "{SHA}" }}\nlines = ["a.py:5-2"]', "ends before it starts"),
        (f'undo_fix = {{ fix = "{SHA}" }}\nlines = ["a.py"]', "must be path:line"),
        (f'undo_fix = {{ fix = "{SHA}" }}\nseverity = "high"', "Extra inputs are not permitted"),
    ],
)
def test_a_bug_case_that_is_not_one_is_refused(tmp_path: Path, case: str, refusal: str) -> None:
    path = bench_file(tmp_path, f'[[cases]]\nname = "c"\nkind = "bug"\ntitle = "T"\n{case}')
    with pytest.raises(BenchError, match=refusal):
        bench.load(path)


@pytest.mark.parametrize(
    ("case", "refusal"),
    [
        (f'replay = {{ base = "{SHA}", head = "{OTHER}" }}\nlines = ["a.py:1"]', "has no bug, so no lines"),
        (f'undo_fix = {{ fix = "{SHA}" }}', "undoes a fix, so it is a bug case"),
    ],
)
def test_a_clean_case_with_a_bug_is_refused(tmp_path: Path, case: str, refusal: str) -> None:
    path = bench_file(tmp_path, f'[[cases]]\nname = "c"\nkind = "clean"\ntitle = "T"\n{case}')
    with pytest.raises(BenchError, match=refusal):
        bench.load(path)


def test_two_cases_of_one_name_are_refused(tmp_path: Path) -> None:
    case = f'[[cases]]\nname = "c"\nkind = "bug"\ntitle = "T"\nundo_fix = {{ fix = "{SHA}" }}\n'
    with pytest.raises(BenchError, match="case names c are used more than once"):
        bench.load(bench_file(tmp_path, case + case))


def test_a_bench_with_no_reviewer_is_refused(tmp_path: Path) -> None:
    case = f'[[cases]]\nname = "c"\nkind = "bug"\ntitle = "T"\nundo_fix = {{ fix = "{SHA}" }}\n'
    with pytest.raises(BenchError, match="reviewers"):
        bench.load(bench_file(tmp_path, case, reviewers=[]))


def test_cases_are_chosen_by_name_and_split_in_the_files_order(tmp_path: Path) -> None:
    cases = "".join(
        f'[[cases]]\nname = "{name}"\nkind = "bug"\ntitle = "T"\nsplit = "{split}"\nundo_fix = {{ fix = "{SHA}" }}\n'
        for name, split in (("a", "tune"), ("b", "holdout"), ("c", "tune"))
    )
    found = bench.load(bench_file(tmp_path, cases)).file.cases
    assert [c.name for c in bench.chosen(found, ("c", "a"), None)] == ["a", "c"]
    assert [c.name for c in bench.chosen(found, (), "tune")] == ["a", "c"]
    with pytest.raises(BenchError, match="no case named x"):
        bench.chosen(found, ("x",), None)
    with pytest.raises(BenchError, match="no case is left"):
        bench.chosen(found, ("b",), "tune")


@pytest.mark.parametrize(
    ("lines", "side", "near"),
    [
        ((10, 10), Side.HEAD, True),
        ((7, 7), Side.HEAD, True),
        ((6, 6), Side.HEAD, False),
        ((15, 15), Side.HEAD, True),
        ((16, 20), Side.HEAD, False),
        ((1, 30), Side.HEAD, True),
        ((10, 10), Side.BASE, False),
    ],
)
def test_a_spot_is_near_lines_within_the_tolerance_on_its_side(
    lines: tuple[int, int],
    side: Side,
    *,
    near: bool,
) -> None:
    spot = Spot.parse("src/retry.py:10-12", Side.HEAD)
    assert spot.near("src/retry.py", *lines, side, 3) is near
    assert not spot.near("src/other.py", 10, 10, Side.HEAD, 3)
    assert str(spot) == "src/retry.py:10-12"
