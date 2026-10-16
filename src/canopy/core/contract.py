"""The pieces every agent result contract is built from (D026): bounded text, plain URLs, and the result line.

An agent's result is untrusted, so every field of a contract is bounded and validated before anything reads it. A result
that does not validate is no result: each caller decides what that run's status becomes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast

from pydantic import AfterValidator, BaseModel, ValidationError


def bounded(limit: int) -> AfterValidator:
    """Cut a string to at most `limit` characters, marking the cut with "...".

    Returns:
        A validator that keeps a string within `limit` unchanged and ends a longer one in "...".
    """
    return AfterValidator(lambda v: v if len(v) <= limit else v[: limit - 3] + "...")


def _one_line(value: str) -> str:
    return " ".join(value.split())


# Every run of whitespace, line breaks included, becomes one space.
one_line = AfterValidator(_one_line)


def plain_url(value: str, limit: int) -> bool:
    """Whether `value` is a plain `https://` URL of at most `limit` characters, with no whitespace.

    Returns:
        True when `value` starts with `https://`, fits in `limit`, and has no whitespace.
    """
    return value.startswith("https://") and len(value) <= limit and not any(c.isspace() for c in value)


def url(limit: int) -> AfterValidator:
    """Refuse a string that is not a plain `https://` URL of at most `limit` characters.

    Returns:
        A validator that passes a plain URL through unchanged and raises `ValueError` on anything else, which pydantic
        reports as a validation error.
    """

    def check(value: str) -> str:
        if not plain_url(value, limit):
            raise ValueError(f"must be a plain https:// URL of at most {limit} characters")
        return value

    return AfterValidator(check)


def last_line[M: BaseModel](model: type[M], text: str) -> M | None:
    """Parse the last line of `text` that starts with `{` as `model`. None if there is none or it is invalid.

    Lines after it that are not JSON objects, such as a runtime plugin's notices, are passed over (DESIGN §13). An
    invalid object is not: a result the agent got wrong is no result, never an earlier line's.

    Returns:
        The validated result, or None when no line starts with `{` or the last one does not validate as `model`.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip().startswith("{")]
    if not lines:
        return None
    return stored(model, lines[-1])


def stored[M: BaseModel](model: type[M], result_json: object) -> M | None:
    """Read a result the journal stored as `model`. None if there is none: the run ended without a valid result.

    Returns:
        The validated result, or None when `result_json` is not a non-empty string or does not validate as `model`.
    """
    if not isinstance(result_json, str) or not result_json:
        return None
    try:
        return model.model_validate_json(result_json)
    except ValidationError:
        return None


def stored_object(result_json: str | None) -> dict[str, object]:
    """A run's stored result as an object; {} when it has none or it does not parse. Its values are still untrusted.

    Returns:
        The parsed object with its keys as strings, or {} when `result_json` is empty, not JSON, or not an object.
    """
    if not result_json:
        return {}
    try:
        parsed: object = json.loads(result_json)
    except json.JSONDecodeError:
        return {}
    return {str(k): v for k, v in cast("dict[object, object]", parsed).items()} if isinstance(parsed, dict) else {}


def stored_prs(result: Mapping[str, object]) -> list[str]:
    """The PRs a stored result names, each a plain printable https:// URL; anything else is left out.

    Returns:
        The values of `prs` when it is an object, otherwise `pr` alone, keeping only the plain URLs among them.
    """
    prs = result.get("prs")
    urls = list(cast("dict[str, object]", prs).values()) if isinstance(prs, dict) else [result.get("pr")]
    return [u for u in urls if isinstance(u, str) and u.startswith("https://") and u.isprintable() and " " not in u]
