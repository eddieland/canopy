"""JSON-lines logging to `<state_dir>/canopy.log`.

Every record carries `tick_id` (null outside a tick). Code logs through `for_tick`, which returns an adapter that stamps
the id, so a tick's lines can be pulled out with one filter.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
import stat
from collections.abc import Mapping, MutableMapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO, override

LOG_FILE_NAME = "canopy.log"
#: A rotated log's name, `canopy.log.1` the newest, and its number.
ROTATED_RE = re.compile(rf"{re.escape(LOG_FILE_NAME)}\.(\d+)")
_LOGGER = "canopy"
_STANDARD_ATTRS = frozenset(vars(logging.makeLogRecord({})))


class JsonFormatter(logging.Formatter):
    """Formats a record as one JSON object with `ts`, `level`, `msg`, `tick_id`, and any extras."""

    @override
    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "msg": record.getMessage(),
            "tick_id": getattr(record, "tick_id", None),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and key not in line:
                line[key] = value
        if record.exc_info:
            line["exc"] = self.formatException(record.exc_info)
        return json.dumps(line, default=str)


class TickAdapter(logging.LoggerAdapter[logging.Logger]):
    """A logger adapter that stamps every record with its tick id."""

    @override
    def process(self, msg: Any, kwargs: MutableMapping[str, Any]) -> tuple[Any, MutableMapping[str, Any]]:
        extra: Mapping[str, object] = kwargs.get("extra") or {}
        kwargs["extra"] = {**(self.extra or {}), **extra}
        return msg, kwargs


def configure(state_dir: Path) -> None:
    """Send the `canopy` logger to `<state_dir>/canopy.log`, replacing any handler from an earlier call.

    The handler reopens the file once it has been moved, so every process follows the tick's `rotate`.
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(_LOGGER)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    handler = logging.handlers.WatchedFileHandler(state_dir / LOG_FILE_NAME, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def rotate(state_dir: Path, *, max_bytes: int, keep: int, name: str = LOG_FILE_NAME) -> list[Path]:
    """Rotate `canopy.log`, or the file `name`, once past `max_bytes`, and drop rotated ones past the newest `keep`.

    The log moves to `canopy.log.1` and each rotated file up one; `keep` 0 keeps every one, and `max_bytes` 0 never
    rotates. Only regular files are moved or removed, never a link, and a move never replaces what is at its name. Run
    by one process alone, the tick under its lock: the others' handlers reopen the log once it has moved (`configure`).

    Returns:
        The rotated files it removed.

    Raises:
        FileExistsError: Something not a regular file holds a rotated file's name, so nothing could move up to it.
    """
    current = state_dir / name
    size = _regular_size(current)
    due = size is not None and max_bytes > 0 and size > max_bytes
    pattern = re.compile(rf"{re.escape(name)}\.(\d+)")
    rotated = sorted(
        ((int(m[1]), path) for path in state_dir.iterdir() if (m := pattern.fullmatch(path.name)) is not None),
        reverse=True,
    )
    removed: list[Path] = []
    # The oldest first, so each moves to a name the one before it has left.
    for index, path in rotated:
        if _regular_size(path) is None:
            continue
        after = index + 1 if due else index
        if keep and after > keep:
            path.unlink()
            removed.append(path)
        elif due:
            _move(path, state_dir / f"{name}.{after}")
    if due:
        _move(current, state_dir / f"{name}.1")
    return removed


def for_tick(tick_id: int | None) -> TickAdapter:
    """Return a logger that stamps records with `tick_id`."""
    return TickAdapter(logging.getLogger(_LOGGER), {"tick_id": tick_id})


def write_private(path: Path, text: str) -> None:
    """Write `text` to `path`, readable only by the operator (TRUST_MODEL T2), as `open_private` opens it."""
    with open_private(path) as f:
        f.write(text)


def open_private(path: Path) -> TextIO:
    """Open `path` for writing from empty, readable only by the operator (TRUST_MODEL T2).

    The mode is set on the open file, so a file that already existed with a wider mode is narrowed too, and a symlink
    at `path` is refused rather than followed.

    Returns:
        The file, open for writing text; the caller closes it.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    f = os.fdopen(fd, "w", encoding="utf-8")
    try:
        os.fchmod(f.fileno(), 0o600)
    except BaseException:
        f.close()
        raise
    return f


def private_dir(path: Path) -> bool:
    """Return whether `path` is a directory only the operator can use: not a symlink, theirs, no group or other bits.

    canopy creates its own directories that way. One that is not, such as a `.canopy/` a git checkout created, came from
    someone else and may hold what they chose (DESIGN §18).
    """
    try:
        st = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() and st.st_mode & 0o077 == 0


def _regular_size(path: Path) -> int | None:
    try:
        found = path.lstat()
    except FileNotFoundError:
        return None
    return found.st_size if stat.S_ISREG(found.st_mode) else None


def _move(source: Path, target: Path) -> None:
    # A rename replaces what is at its target, and what is there was skipped as no regular file: a link stays a link.
    if os.path.lexists(target):
        raise FileExistsError(f"{target} is in the way of rotating {source.name}")
    source.rename(target)
