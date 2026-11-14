"""What became of each signal's exports: kept in the state file for `canopy status`, and counted to ride the metrics."""

from __future__ import annotations

import stat
from typing import TYPE_CHECKING
from unittest import mock

from canopy.infra import exports

if TYPE_CHECKING:
    from pathlib import Path

#: Where the ledgers in these tests send spans.
TO = "http://127.0.0.1:4318/v1/traces"


def test_a_refused_export_is_kept_until_one_is_taken(tmp_path: Path) -> None:
    ledger = exports.Ledger(tmp_path, exports.Signal.TRACES, TO)
    assert exports.read(tmp_path) == {}
    ledger.noted(took=False, why="HTTP 503")
    refused = exports.read(tmp_path)[exports.Signal.TRACES]
    assert (refused.to, refused.error, refused.sent_at, refused.failing) == (TO, "HTTP 503", None, True)
    # Kept by another process, as each process keeps a ledger of its own.
    exports.Ledger(tmp_path, exports.Signal.TRACES, TO).noted(took=True)
    taken = exports.read(tmp_path)[exports.Signal.TRACES]
    assert (taken.failed_at, taken.error, taken.failing) == (refused.failed_at, "HTTP 503", False)
    assert stat.S_IMODE((tmp_path / exports.STATE_FILE_NAME).stat().st_mode) == exports.FILE_MODE
    assert exports.Signal.METRICS not in exports.read(tmp_path)


def test_an_outcome_that_holds_is_kept_again_only_after_a_while(tmp_path: Path) -> None:
    ledger = exports.Ledger(tmp_path, exports.Signal.METRICS, TO)
    ledger.noted(took=True)
    first = exports.read(tmp_path)[exports.Signal.METRICS].sent_at
    ledger.noted(took=True)
    assert exports.read(tmp_path)[exports.Signal.METRICS].sent_at == first
    # An outcome that changes is kept at once.
    ledger.noted(took=False, why="URLError")
    assert exports.read(tmp_path)[exports.Signal.METRICS].failing
    with mock.patch.object(exports, "REFRESH_SECONDS", 0):
        ledger.noted(took=True)
        ledger.noted(took=True)
    assert exports.read(tmp_path)[exports.Signal.METRICS].sent_at != first


def test_a_new_destination_starts_its_record_anew(tmp_path: Path) -> None:
    exports.Ledger(tmp_path, exports.Signal.TRACES, TO).noted(took=False, why="HTTP 503")
    exports.Ledger(tmp_path, exports.Signal.TRACES, "/state/traces.jsonl").noted(took=True)
    record = exports.read(tmp_path)[exports.Signal.TRACES]
    assert (record.to, record.failed_at, record.error) == ("/state/traces.jsonl", None, None)


def test_a_state_file_that_cannot_be_read_says_nothing_and_fails_nothing(tmp_path: Path) -> None:
    (tmp_path / exports.STATE_FILE_NAME).write_text("not json")
    assert exports.read(tmp_path) == {}
    exports.Ledger(tmp_path, exports.Signal.TRACES, TO).noted(took=True)
    assert exports.read(tmp_path)[exports.Signal.TRACES].sent_at is not None
    # A state file that cannot be written loses the record, and nothing else.
    (tmp_path / "file").touch()
    exports.Ledger(tmp_path / "file", exports.Signal.TRACES, TO).noted(took=False)


def test_counts_that_rode_an_export_are_taken_off_and_the_rest_wait(tmp_path: Path) -> None:
    exports.forget()
    traces = exports.Ledger(tmp_path, exports.Signal.TRACES, TO)
    traces.noted(took=True)
    traces.noted(took=False)
    traces.dropped()
    carried = exports.riding(sending=exports.Signal.METRICS)
    assert dict(carried.exports) == {
        (exports.Signal.TRACES, exports.Outcome.SENT): 1,
        (exports.Signal.TRACES, exports.Outcome.FAILED): 1,
        (exports.Signal.METRICS, exports.Outcome.SENT): 1,
    }
    assert carried.spans_dropped == 1
    # Counted while the export that carried the rest was on its way: it waits for the next.
    traces.noted(took=True)
    exports.rode(carried)
    left = exports.riding()
    assert (dict(left.exports), left.spans_dropped) == ({(exports.Signal.TRACES, exports.Outcome.SENT): 1}, 0)
    assert left.start_ns == carried.end_ns
