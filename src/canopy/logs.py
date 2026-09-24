"""JSON-lines logging to `<state_dir>/canopy.log`.

Every record carries `tick_id` (null outside a tick). Code logs through `for_tick`, which returns an adapter that stamps
the id, so a tick's lines can be pulled out with one filter.
"""

from __future__ import annotations

import json
import logging
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
