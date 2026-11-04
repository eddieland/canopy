"""Tests of `--shard`, which runs one of CI's slices of the suite (tests/conftest.py)."""

from __future__ import annotations

import sys

import pytest

from canopy.infra import procs

#: A package whose tests collect in well under a second, so collecting it a few times stays quick.
TARGET = "tests/canopy/infra"


def test_the_slices_together_are_every_test_once() -> None:
    """Each test falls in exactly one slice, so CI's slices together run the whole suite, and no test twice."""
    slices = [_collected(f"--shard={index}/3") for index in (1, 2, 3)]
    assert all(slices), "each slice holds some of the tests"
    assert sorted(node for nodes in slices for node in nodes) == sorted(_collected())


def test_a_parametrized_tests_cases_share_a_slice() -> None:
    """Syrupy counts a snapshot as one of a test's whatever its parameters, so a test's cases are never split up."""
    slices = [{node.partition("[")[0] for node in _collected(f"--shard={index}/3")} for index in (1, 2, 3)]
    assert any("[" in node for node in _collected()), f"{TARGET} has a parametrized test"
    assert sum(len(functions) for functions in slices) == len(set[str]().union(*slices)), "each function in one slice"


def test_a_slice_is_the_same_whatever_else_was_collected() -> None:
    """A test's slice depends on its id alone, so every xdist worker, and a narrower run, agrees on it."""
    whole = _collected("--shard=2/3")
    one_module = [node for node in whole if node.startswith(f"{TARGET}/test_procs.py")]
    assert one_module
    assert _collected("--shard=2/3", path=f"{TARGET}/test_procs.py") == one_module


@pytest.mark.parametrize("shard", ["0/3", "4/3", "1", "a/b", "1/0"])
def test_a_shard_that_names_no_slice_is_refused(shard: str) -> None:
    """A malformed `--shard` is a usage error, so a CI job given a wrong one fails instead of running no test."""
    result = procs.SubprocessRunner().run(_pytest(f"--shard={shard}", path=TARGET))
    assert result.returncode == pytest.ExitCode.USAGE_ERROR
    assert "--shard must be I/N" in result.stderr


def _collected(*args: str, path: str = TARGET) -> list[str]:
    """The node ids pytest collects under `path` with `args`."""
    result = procs.SubprocessRunner().run(_pytest(*args, path=path))
    assert result.ok, result.stderr
    return [line for line in result.stdout.splitlines() if "::" in line]


def _pytest(*args: str, path: str) -> list[str]:
    """Collect `path` with `args` in a pytest of its own, as quietly as it lists node ids."""
    return [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *args, path]
