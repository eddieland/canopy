"""A chore's result contract (DESIGN §19): the last line of its agent's stdout, validated before anything reads it.

A chore reads text from people outside the operator's queue, so everything it reports is untrusted and bounded. A
result that does not validate is `unknown`, and none of its findings are recorded.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictStr, ValidationError

MAX_SUMMARY = 2000
MAX_DETAIL = 2000
MAX_TITLE = 200
MAX_ID = 200
MAX_LINK = 500
MAX_FINDINGS = 20
# Stable across runs for the same problem, so it identifies the finding on the attention list and in notifications.
FINDING_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*")


def _cut(limit: int) -> AfterValidator:
    return AfterValidator(lambda v: v if len(v) <= limit else v[: limit - 3] + "...")


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _finding_id(value: str) -> str:
    if len(value) > MAX_ID or not FINDING_ID_RE.fullmatch(value):
        raise ValueError(f"must match {FINDING_ID_RE.pattern} and be at most {MAX_ID} characters")
    return value


def _link(value: str) -> str:
    if not value.startswith("https://") or len(value) > MAX_LINK or any(c.isspace() for c in value):
        raise ValueError(f"must be a plain https:// URL of at most {MAX_LINK} characters")
    return value


class Finding(BaseModel):
    """One problem a chore found, which stays on the attention list while later `ok` runs report its id."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    id: Annotated[StrictStr, AfterValidator(_finding_id)]
    title: Annotated[StrictStr, AfterValidator(_one_line), _cut(MAX_TITLE)]
    detail: Annotated[StrictStr, _cut(MAX_DETAIL)] = ""
    link: Annotated[StrictStr, AfterValidator(_link)] | None = None


def _unique_ids(findings: list[Finding]) -> list[Finding]:
    ids = [f.id for f in findings]
    if len(set(ids)) != len(ids):
        raise ValueError("finding ids must be unique within a run")
    return findings


class ChoreResult(BaseModel):
    """`ok` means the chore did its check, and no findings means nothing needs a human; `failed` means it could not."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    status: Literal["ok", "failed"]
    summary: Annotated[StrictStr, _cut(MAX_SUMMARY)] = ""
    findings: Annotated[list[Finding], Field(max_length=MAX_FINDINGS), AfterValidator(_unique_ids)] = []


def parse(stdout: str) -> ChoreResult | None:
    """Parse the last non-empty line of `stdout` as a chore's result. None if it is missing or invalid."""
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        return None
    try:
        return ChoreResult.model_validate_json(lines[-1])
    except ValidationError:
        return None


def stored(result_json: object) -> ChoreResult | None:
    """Read a result the journal stored, or None if there is none (a run that ended without a valid result)."""
    if not isinstance(result_json, str) or not result_json:
        return None
    try:
        return ChoreResult.model_validate_json(result_json)
    except ValidationError:
        return None


CONTRACT = (
    '{"status":"ok|failed","summary":"one paragraph",'
    '"findings":[{"id":"stable/id","title":"one line","detail":"a paragraph","link":"https://..."}]}'
)
