"""The JSON OpenCode prints, read from among what else its plugins print to the same stdout.

A plugin OpenCode loads may print to stdout before OpenCode's own output or after it, and the operator may not be free
to remove it. OpenCode's output starts a line, so each line a pattern picks is read as the start of one JSON value, and
the first that validates is OpenCode's. None of it is quoted back: what a plugin prints, or the config, may hold a
secret.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import ValidationError

if TYPE_CHECKING:
    import re
    from collections.abc import Callable


def among[T](printed: str, starts: re.Pattern[str], validate: Callable[[str], T]) -> T | None:
    """Read `printed` whole with `validate`, or else the first JSON value at a match of `starts` that it takes.

    Returns:
        What `validate` made of it, or None when neither the whole nor any value it starts is one.
    """
    try:
        return validate(printed)
    except ValidationError:
        pass
    decoder = json.JSONDecoder()
    for start in starts.finditer(printed):
        try:
            _, end = decoder.raw_decode(printed, start.start())
            return validate(printed[start.start() : end])
        except (json.JSONDecodeError, ValidationError):
            continue
    return None
