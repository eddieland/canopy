"""A run asked again for its result: how the two starts' processes are read as one."""

from __future__ import annotations

from unittest import mock

import pytest

from canopy.core import ask_again, run_result
from canopy.infra import procs
from canopy.runs.task_run import CONTRACT
from canopy.runtime.implementation import Version

#: How the second start is asked, whatever the first printed.
AGAIN = ask_again.Again("report your result", ("--session=ses_1",), 120.0)


def ran(stdout: str, *, returncode: int = 0, timed_out: bool = False) -> procs.Result:
    """A start's process, as the runner returns it."""
    return procs.Result(("opencode",), returncode, stdout, "", timed_out=timed_out)


def asked_again(first: procs.Result, second: procs.Result) -> procs.Result:
    """The process `ask_again.run` returns for a run whose first start reported nothing and whose second is `second`."""
    starts = iter((first, second))
    with (
        mock.patch.object(ask_again, "_again", autospec=True, return_value=AGAIN),
        mock.patch.object(run_result, "reported", autospec=True, return_value=""),
    ):
        done, _ = ask_again.run(
            lambda _again: next(starts),
            CONTRACT.asked(()),
            server="canopy_run",
            version=Version.TWO,
            seconds=600,
        )
    return done


@pytest.mark.parametrize(("first", "joined"), [("a\n", "a\nb\n"), ("a", "a\nb\n"), ("", "b\n")])
def test_the_second_start_is_read_from_a_line_of_its_own(first: str, joined: str) -> None:
    """A first start whose last event was cut short does not swallow the second's first."""
    assert asked_again(ran(first), ran("b\n")).stdout == joined


def test_a_second_start_that_runs_out_the_time_is_the_runs_timeout() -> None:
    """It timed out, so the run did, though its first start exited 0."""
    done = asked_again(ran("a\n"), ran("b\n", returncode=-9, timed_out=True))
    assert (done.timed_out, done.returncode) == (True, -9)


def test_a_second_start_that_ends_in_time_keeps_the_first_starts_exit() -> None:
    """The first start's exit stands: the second only says what the first left unsaid."""
    done = asked_again(ran("a\n"), ran("b\n", returncode=3))
    assert (done.timed_out, done.returncode) == (False, 0)
