"""JSON-lines logging to `<state_dir>/canopy.log`.

Every record carries `tick_id` (null outside a tick). Code logs through `for_tick`, which returns an adapter that stamps
the id, so a tick's lines can be pulled out with one filter.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping, MutableMapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, override

LOG_FILE_NAME = "canopy.log"
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
    """Send the `canopy` logger to `<state_dir>/canopy.log`, replacing any handler from an earlier call."""
    state_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(_LOGGER)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    handler = logging.FileHandler(state_dir / LOG_FILE_NAME, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def for_tick(tick_id: int | None) -> TickAdapter:
    """Return a logger that stamps records with `tick_id`."""
    return TickAdapter(logging.getLogger(_LOGGER), {"tick_id": tick_id})


def write_private(path: Path, text: str) -> None:
    """Write `text` to `path`, readable only by the operator (TRUST_MODEL T2).

    The mode is set on the open file, so a file that already existed with a wider mode is narrowed too, and a symlink
    at `path` is refused rather than followed.
    """
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(text)
