"""What became of each signal's exports: counted for the metrics to carry, and kept for `canopy status` to read.

An exporter keeps a `Ledger` of its signal, and tells it how each export went: taken by the endpoint or written to the
file, or not, and for spans, each one the batch queue had no room for. The ledger counts them for this process, and
the counts ride the next export of metrics that works (`riding`, `rode`), so a collector learns what it did not get
once it gets anything. It also keeps when each signal was last taken and last refused in `STATE_FILE_NAME`, in the
state directory, which `canopy status` reads from a process of its own: the counts live and die with the process that
made them, and the file is what outlives it. Every value in either is canopy's own, never text it read (D132).

This module loads no OpenTelemetry, so `canopy status` reads the file without it.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.infra import lock

if TYPE_CHECKING:
    from collections.abc import Mapping


class Signal(StrEnum):
    """A kind of telemetry canopy sends: a label of `EXPORTS`, and a key of the state file."""

    TRACES = "traces"
    METRICS = "metrics"


class Outcome(StrEnum):
    """How one export went: a label of `EXPORTS`."""

    #: Taken by the endpoint, with a 2xx, or written whole to the file.
    SENT = "sent"
    #: Not taken: what it held is dropped, never sent again.
    FAILED = "failed"


#: The counter of exports, by signal and outcome, which the metrics carry: kept here, not by OpenTelemetry, so a count
#: that rode an export the endpoint did not take rides the next.
EXPORTS = "canopy.telemetry.exports"
#: What `EXPORTS` counts, sent with every export.
EXPORTS_DESCRIPTION = "Exports of telemetry, by signal and outcome: sent, or failed and dropped."
#: The counter of spans the batch queue had no room for, dropped before any export.
SPANS_DROPPED = "canopy.telemetry.spans.dropped"
#: What `SPANS_DROPPED` counts, sent with every export that carries it.
SPANS_DROPPED_DESCRIPTION = "Spans dropped before any export, the queue of spans waiting to be sent being full."
#: The file in the state directory that keeps how each signal's exports last went, for `canopy status`.
STATE_FILE_NAME = "telemetry.json"
#: The lock writers of the state file hold, so two processes never lose each other's update.
LOCK_FILE_NAME = "telemetry.lock"
#: How long a ledger leaves the state file as it is while its outcome holds: a file of spans is written to as each span
#: ends, and the file need only say about when.
REFRESH_SECONDS = 10.0
#: Who may read the state file: the operator alone, as the log (TRUST_MODEL T2).
FILE_MODE = 0o600


@dataclass(frozen=True)
class Record:
    """How one signal's exports last went, as the state file keeps it: each a time as `datetime.isoformat` writes it."""

    #: Where the exports went: the endpoint's URL or the file's path, so a record of another destination is not read as
    #: this one's.
    to: str
    #: When an export was last taken, or None if none ever was.
    sent_at: str | None = None
    #: When an export was last refused, or None if none ever was.
    failed_at: str | None = None
    #: Why the last refused export was: an HTTP status or an exception's type, canopy's own words.
    error: str | None = None
    #: When the batch queue last dropped a span, or None if it never did.
    dropped_at: str | None = None

    @property
    def failing(self) -> bool:
        """Whether the last export was refused: one failed, and none was taken since."""
        if self.failed_at is None:
            return False
        return self.sent_at is None or datetime.fromisoformat(self.failed_at) >= datetime.fromisoformat(self.sent_at)


class Ledger:
    """How one signal's exports go, in this process, to one destination: counted to ride the metrics, and kept."""

    def __init__(self, state_dir: Path, signal: Signal, to: str) -> None:
        """Keep `signal`'s exports to `to`, the endpoint's URL or the file's path, in `state_dir`'s state file."""
        self.state_dir = state_dir
        self.signal = signal
        self.to = to
        #: How the last export this ledger kept went, and when it kept it, by `time.monotonic`.
        self._kept: tuple[bool, float] | None = None
        #: When this ledger last kept a dropped span.
        self._dropped_kept: float | None = None
        self._warned = False

    def noted(self, *, took: bool, why: str = "") -> None:
        """Count one export, taken or not, and keep it in the state file unless it says as much, lately."""
        _tally.add((self.signal, Outcome.SENT if took else Outcome.FAILED))
        now = time.monotonic()
        if self._kept is not None and self._kept[0] == took and now - self._kept[1] < REFRESH_SECONDS:
            return
        self._kept = (took, now)
        stamp = _stamp()
        self._keep({"sent_at": stamp} if took else {"failed_at": stamp, "error": why or None})

    def dropped(self) -> None:
        """Count one span the batch queue had no room for, and keep when it was, unless it was kept lately."""
        _tally.drop()
        now = time.monotonic()
        if self._dropped_kept is not None and now - self._dropped_kept < REFRESH_SECONDS:
            return
        self._dropped_kept = now
        self._keep({"dropped_at": _stamp()})

    def _keep(self, changes: Mapping[str, str | None]) -> None:
        """Write `changes` to this signal's record, under the lock; a record of another destination starts anew."""
        path = self.state_dir / STATE_FILE_NAME
        try:
            with lock.hold(self.state_dir / LOCK_FILE_NAME, wait=True):
                state = _load(path)
                was = state.get(self.signal.value)
                record = dict(was) if isinstance(was, dict) and was.get("to") == self.to else {"to": self.to}
                state[self.signal.value] = {**record, **changes}
                _write(path, state)
        # Telemetry never fails what canopy was doing: the counts still ride, and status says nothing new.
        except OSError as e:
            if not self._warned:
                self._warned = True
                _LOG.warning(
                    "telemetry's state not kept; canopy status cannot say how exports go",
                    extra={"file": str(path), "error": type(e).__name__},
                )


@dataclass(frozen=True)
class Riding:
    """What this process counted since its counts last rode an export of metrics: a snapshot `riding` takes."""

    #: Exports, by signal and outcome; none of a pair that counted none.
    exports: Mapping[tuple[Signal, Outcome], int]
    #: Spans the batch queue dropped.
    spans_dropped: int
    #: When the counts started, in nanoseconds since the epoch: the delta's start.
    start_ns: int
    #: When the snapshot was taken: the delta's end, and the next one's start once it rode.
    end_ns: int


def riding(*, sending: Signal | None = None) -> Riding:
    """What this process counted, to ride an export of metrics; `sending` counts that export too, as sent.

    The export counts itself, so the last one a process makes, as it exits, is counted too. Once it is taken, `rode`
    takes what it carried off the counts; if it is not, the export counts itself failed, and the rest waits.

    Returns:
        The snapshot.
    """
    return _tally.snapshot(sending)


def rode(carried: Riding) -> None:
    """Take what `carried` held off this process's counts: an export of metrics that carried it was taken."""
    _tally.subtract(carried)


def forget() -> None:
    """Drop this process's counts, as metrics start or stop: with metrics off, nothing would carry them."""
    _tally.reset()


def read(state_dir: Path) -> dict[Signal, Record]:
    """How each signal's exports last went, as the state file in `state_dir` keeps them.

    Returns:
        A record of each signal that kept one; none of a signal never sent, or when the file cannot be read.
    """
    state = _load(state_dir / STATE_FILE_NAME)
    found: dict[Signal, Record] = {}
    for signal in Signal:
        kept = state.get(signal.value)
        if not isinstance(kept, dict) or not isinstance(kept.get("to"), str):
            continue
        fields = {
            key: value
            for key in ("sent_at", "failed_at", "error", "dropped_at")
            if isinstance(value := kept.get(key), str)
        }
        found[signal] = Record(to=kept["to"], **fields)
    return found


class _Tally:
    """This process's counts, which every exporter's thread adds to and the metric reader's thread takes off."""

    def __init__(self) -> None:
        """Start with nothing counted."""
        self._lock = threading.Lock()
        self._exports: dict[tuple[Signal, Outcome], int] = {}
        self._dropped = 0
        self._start_ns = time.time_ns()

    def add(self, key: tuple[Signal, Outcome]) -> None:
        """Count one export."""
        with self._lock:
            self._exports[key] = self._exports.get(key, 0) + 1

    def drop(self) -> None:
        """Count one dropped span."""
        with self._lock:
            self._dropped += 1

    def snapshot(self, sending: Signal | None) -> Riding:
        """What is counted now, with one export of `sending` sent, if any.

        Returns:
            The snapshot.
        """
        with self._lock:
            exports = dict(self._exports)
            if sending is not None:
                exports[sending, Outcome.SENT] = exports.get((sending, Outcome.SENT), 0) + 1
            return Riding(exports, self._dropped, self._start_ns, time.time_ns())

    def subtract(self, carried: Riding) -> None:
        """Take what `carried` held off the counts, which start again from when it was taken."""
        with self._lock:
            for key, n in carried.exports.items():
                left = self._exports.get(key, 0) - n
                if left > 0:
                    self._exports[key] = left
                else:
                    self._exports.pop(key, None)
            self._dropped = max(0, self._dropped - carried.spans_dropped)
            self._start_ns = max(self._start_ns, carried.end_ns)

    def reset(self) -> None:
        """Drop every count."""
        with self._lock:
            self._exports.clear()
            self._dropped = 0
            self._start_ns = time.time_ns()


_tally = _Tally()
_LOG = logging.getLogger("canopy")


def _stamp() -> str:
    """Now, as the state file keeps a time: UTC, to the microsecond, so two outcomes a moment apart keep their order.

    Returns:
        The time.
    """
    return datetime.now(UTC).isoformat()


def _load(path: Path) -> dict[str, object]:
    """The state file's object, or an empty one when it is missing or cannot be read.

    Returns:
        The object.
    """
    try:
        loaded: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): v for k, v in loaded.items()} if isinstance(loaded, dict) else {}


def _write(path: Path, state: Mapping[str, object]) -> None:
    """Write `state` whole to a file of its own and move it into place, so a reader never sees half of it."""
    fd, made = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.fchmod(fd, FILE_MODE)
        with os.fdopen(fd, "w", encoding="utf-8") as made_file:
            json.dump(state, made_file, separators=(",", ":"))
        Path(made).replace(path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            Path(made).unlink()
