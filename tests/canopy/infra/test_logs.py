"""`canopy.log`: each line naming its span while tracing is on, rotated past a size (DESIGN §26), and followed."""

import json
import logging
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from canopy.infra import logs, tracing
from tests.canopy.helpers import spans

NAME = logs.LOG_FILE_NAME
#: Reads each line the log holds.
type Lines = Callable[[], list[dict[str, Any]]]


@pytest.fixture
def logged(tmp_path: Path) -> Iterator[Lines]:
    """The log sent to `tmp_path`, in a process that inherited no trace; yields a reader of each line it holds."""
    with mock.patch.dict(os.environ):
        os.environ.pop(tracing.TRACEPARENT, None)
        logs.configure(tmp_path)
        try:
            yield lambda: [json.loads(line) for line in (tmp_path / NAME).read_text().splitlines()]
        finally:
            tracing.configure(tmp_path, "off")
            logger = logging.getLogger("canopy")
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                handler.close()


def test_a_line_logged_in_a_span_names_it_as_the_traces_do(logged: Lines, tmp_path: Path) -> None:
    tracing.configure(tmp_path, "file")
    log = logs.for_tick(7)
    log.info("outside")
    with tracing.span("tick"), tracing.span("state"):
        # An extra cannot name a span the line was not logged in.
        log.info("inside", extra={"trace_id": "spoofed", "span_id": "spoofed"})

    outside, inside = logged()
    state, tick = spans(tmp_path / tracing.TRACES_FILE_NAME)
    assert "trace_id" not in outside
    assert "span_id" not in outside
    assert (inside["trace_id"], inside["span_id"]) == (state["traceId"], state["spanId"])
    assert tick["traceId"] == state["traceId"]


def test_a_line_names_no_span_while_tracing_is_off(logged: Lines) -> None:
    with tracing.span("tick"):
        logs.for_tick(7).info("inside", extra={"trace_id": "spoofed"})

    [line] = logged()
    assert set(line) == {"ts", "level", "msg", "tick_id"}


def write(state: Path, suffix: str, text: str) -> None:
    (state / f"{NAME}{suffix}").write_text(text)


def contents(state: Path) -> dict[str, str]:
    """Each log file in `state` and what it holds, by name; a link by what it points to."""
    return {
        p.name: f"-> {p.readlink()}" if p.is_symlink() else p.read_text()
        for p in sorted(state.iterdir())
        if p.name.startswith(NAME)
    }


def test_a_log_past_its_size_moves_to_one_and_each_rotated_one_up(tmp_path: Path) -> None:
    write(tmp_path, "", "now " * 5)
    write(tmp_path, ".1", "older")
    write(tmp_path, ".2", "oldest")

    removed = logs.rotate(tmp_path, max_bytes=10, keep=3)

    assert removed == []
    assert contents(tmp_path) == {f"{NAME}.1": "now " * 5, f"{NAME}.2": "older", f"{NAME}.3": "oldest"}


def test_a_rotated_log_past_keep_is_removed(tmp_path: Path) -> None:
    write(tmp_path, "", "now " * 5)
    write(tmp_path, ".1", "older")
    write(tmp_path, ".2", "oldest")

    removed = logs.rotate(tmp_path, max_bytes=10, keep=2)

    assert removed == [tmp_path / f"{NAME}.2"]
    assert contents(tmp_path) == {f"{NAME}.1": "now " * 5, f"{NAME}.2": "older"}


def test_a_log_under_its_size_stays_but_one_past_a_lowered_keep_goes(tmp_path: Path) -> None:
    write(tmp_path, "", "now")
    write(tmp_path, ".1", "older")
    write(tmp_path, ".2", "oldest")

    assert logs.rotate(tmp_path, max_bytes=10, keep=1) == [tmp_path / f"{NAME}.2"]
    assert contents(tmp_path) == {NAME: "now", f"{NAME}.1": "older"}


def test_keep_zero_keeps_every_rotated_log(tmp_path: Path) -> None:
    write(tmp_path, "", "now " * 5)
    write(tmp_path, ".1", "older")

    assert logs.rotate(tmp_path, max_bytes=10, keep=0) == []
    assert contents(tmp_path) == {f"{NAME}.1": "now " * 5, f"{NAME}.2": "older"}


def test_a_size_of_zero_never_rotates(tmp_path: Path) -> None:
    write(tmp_path, "", "now " * 5)
    write(tmp_path, ".1", "older")

    assert logs.rotate(tmp_path, max_bytes=0, keep=1) == []
    assert contents(tmp_path) == {NAME: "now " * 5, f"{NAME}.1": "older"}


def test_a_link_is_never_moved_removed_or_replaced(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere"
    target.write_text("keep me")
    write(tmp_path, "", "now " * 5)
    (tmp_path / f"{NAME}.1").symlink_to(target)

    with pytest.raises(FileExistsError, match="in the way"):
        logs.rotate(tmp_path, max_bytes=10, keep=1)

    assert contents(tmp_path) == {NAME: "now " * 5, f"{NAME}.1": f"-> {target}"}
    assert target.read_text() == "keep me"


def test_a_log_that_is_a_link_is_not_rotated(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere"
    target.write_text("now " * 5)
    (tmp_path / NAME).symlink_to(target)

    assert logs.rotate(tmp_path, max_bytes=10, keep=1) == []
    assert contents(tmp_path) == {NAME: f"-> {target}"}


def test_each_process_follows_the_log_to_its_new_file(tmp_path: Path) -> None:
    logs.configure(tmp_path)
    log = logs.for_tick(7)
    try:
        log.info("before")
        logs.rotate(tmp_path, max_bytes=1, keep=1)
        log.info("after")
    finally:
        logger = logging.getLogger("canopy")
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    rotated = [json.loads(line)["msg"] for line in (tmp_path / f"{NAME}.1").read_text().splitlines()]
    current = [json.loads(line)["msg"] for line in (tmp_path / NAME).read_text().splitlines()]
    assert (rotated, current) == (["before"], ["after"])


def test_another_file_rotates_alike_by_its_own_name(tmp_path: Path) -> None:
    traces = tmp_path / "traces.jsonl"
    traces.write_text("span " * 5)
    write(tmp_path, "", "now " * 5)

    assert logs.rotate(tmp_path, max_bytes=10, keep=3, name="traces.jsonl") == []
    assert sorted(p.name for p in tmp_path.iterdir()) == [NAME, "traces.jsonl.1"]
