"""A chore's result contract (DESIGN §19): the last line of its agent's stdout, validated before anything reads it.

A chore reads text from people outside the operator's queue, so everything it reports is untrusted and bounded. A
result that does not validate is `unknown`, and none of its findings are recorded.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictStr

from canopy.core import contract
from canopy.core.contract import bounded, one_line

MAX_SUMMARY = 2000
MAX_DETAIL = 2000
MAX_TITLE = 200
MAX_ID = 200
MAX_LINK = 500
MAX_FINDINGS = 20
# Stable across runs for the same problem, so it identifies the finding on the attention list and in notifications.
FINDING_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*")


def _finding_id(value: str) -> str:
    if len(value) > MAX_ID or not FINDING_ID_RE.fullmatch(value):
        raise ValueError(f"must match {FINDING_ID_RE.pattern} and be at most {MAX_ID} characters")
    return value


class Finding(BaseModel):
    """One problem a chore found, which stays on the attention list while later `ok` runs report its id."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    id: Annotated[StrictStr, AfterValidator(_finding_id)]
    title: Annotated[StrictStr, one_line, bounded(MAX_TITLE)]
    detail: Annotated[StrictStr, bounded(MAX_DETAIL)] = ""
    link: Annotated[StrictStr, contract.url(MAX_LINK)] | None = None


def _unique_ids(findings: list[Finding]) -> list[Finding]:
    ids = [f.id for f in findings]
    if len(set(ids)) != len(ids):
        raise ValueError("finding ids must be unique within a run")
    return findings


class ChoreResult(BaseModel):
    """`ok` means the chore did its check, and no findings means nothing needs a human; `failed` means it could not."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    status: Literal["ok", "failed"]
    summary: Annotated[StrictStr, bounded(MAX_SUMMARY)] = ""
    findings: Annotated[list[Finding], Field(max_length=MAX_FINDINGS), AfterValidator(_unique_ids)] = []


def parse(stdout: str) -> ChoreResult | None:
    """Parse `stdout`'s result line (DESIGN §13) as a chore's result. None if it is missing or invalid."""
    return contract.last_line(ChoreResult, stdout)


def stored(result_json: object) -> ChoreResult | None:
    """Read a result the journal stored, or None if there is none (a run that ended without a valid result)."""
    return contract.stored(ChoreResult, result_json)


CONTRACT = (
    '{"status":"ok|failed","summary":"one paragraph",'
    '"findings":[{"id":"stable/id","title":"one line","detail":"a paragraph","link":"https://..."}]}'
)
