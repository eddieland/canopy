"""The pieces every agent result contract is built from (D026): bounded text, plain URLs, and the last line of stdout.

An agent's result is untrusted, so every field of a contract is bounded and validated before anything reads it. A result
that does not validate is no result: each caller decides what that run's status becomes.
"""

from __future__ import annotations

from pydantic import AfterValidator, BaseModel, ValidationError


def bounded(limit: int) -> AfterValidator:
    """Cut a string to at most `limit` characters, marking the cut with "..."."""
    return AfterValidator(lambda v: v if len(v) <= limit else v[: limit - 3] + "...")


def _one_line(value: str) -> str:
    return " ".join(value.split())


# Every run of whitespace, line breaks included, becomes one space.
one_line = AfterValidator(_one_line)


def plain_url(value: str, limit: int) -> bool:
    """Whether `value` is a plain `https://` URL of at most `limit` characters, with no whitespace."""
    return value.startswith("https://") and len(value) <= limit and not any(c.isspace() for c in value)


def url(limit: int) -> AfterValidator:
    """Refuse a string that is not a plain `https://` URL of at most `limit` characters."""

    def check(value: str) -> str:
        if not plain_url(value, limit):
            raise ValueError(f"must be a plain https:// URL of at most {limit} characters")
        return value

    return AfterValidator(check)


def last_line[M: BaseModel](model: type[M], stdout: str) -> M | None:
    """Parse the last non-empty line of `stdout` as `model`. None if it is missing or invalid."""
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        return None
    return stored(model, lines[-1])


def stored[M: BaseModel](model: type[M], result_json: object) -> M | None:
    """Read a result the journal stored as `model`. None if there is none: the run ended without a valid result."""
    if not isinstance(result_json, str) or not result_json:
        return None
    try:
        return model.model_validate_json(result_json)
    except ValidationError:
        return None
