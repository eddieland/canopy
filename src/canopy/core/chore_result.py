"""A chore's result contract (DESIGN §19): the last line of its agent's stdout, validated before anything reads it.

A chore reads text from people outside the operator's queue, so everything it reports is untrusted and bounded. A
result that does not validate is `unknown`, and none of its findings are recorded. One that lists more findings than its
chore's `max_findings` keeps the first ones and counts the rest in `more_findings` (`capped`). An optional field that is
null or "" is read as missing, so it takes its default.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, cast

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from canopy.core import contract
from canopy.core.contract import bounded, one_line

MAX_SUMMARY = 2000
MAX_DETAIL = 2000
MAX_TITLE = 200
MAX_ID = 200
MAX_LINK = 500
MAX_FINDINGS = 20
# The findings a run lists unless its chore's `max_findings` says otherwise: as many as a person reads at a glance.
DEFAULT_MAX_FINDINGS = 5
# How many findings a run may say it left out. A count, so bounded only to keep nonsense out.
MAX_MORE_FINDINGS = 100_000
# Stable across runs for the same problem, so it identifies the finding on the attention list and in notifications.
FINDING_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*")


# What a chore reports, field by field.
class _Reported(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    @model_validator(mode="before")
    @classmethod
    def _empty_is_missing(cls, value: object) -> object:
        # An agent writes `"link": ""` or `"detail": null` for a field it has nothing for; both mean it left it out.
        if not isinstance(value, dict):
            return value
        optional = {name for name, field in cls.model_fields.items() if not field.is_required()}
        return {
            k: v for k, v in cast("dict[object, object]", value).items() if k not in optional or v not in (None, "")
        }


def _finding_id(value: str) -> str:
    if len(value) > MAX_ID or not FINDING_ID_RE.fullmatch(value):
        raise ValueError(f"must match {FINDING_ID_RE.pattern} and be at most {MAX_ID} characters")
    return value


class Finding(_Reported):
    """One problem a chore found, which stays on the attention list while later `ok` runs report its id."""

    id: Annotated[StrictStr, AfterValidator(_finding_id)]
    title: Annotated[StrictStr, one_line, bounded(MAX_TITLE)]
    detail: Annotated[StrictStr, bounded(MAX_DETAIL)] = ""
    link: Annotated[StrictStr, contract.url(MAX_LINK)] | None = None


def _unique_ids(findings: list[Finding]) -> list[Finding]:
    ids = [f.id for f in findings]
    if len(set(ids)) != len(ids):
        raise ValueError("finding ids must be unique within a run")
    return findings


class ChoreResult(_Reported):
    """`ok` means the chore did its check, and no findings means nothing needs a human; `failed` means it could not."""

    status: Literal["ok", "failed"]
    summary: Annotated[StrictStr, bounded(MAX_SUMMARY)] = ""
    findings: Annotated[list[Finding], Field(max_length=MAX_FINDINGS), AfterValidator(_unique_ids)] = []
    # How many more findings it had than it listed, the least important ones, left out to stay under `max_findings`.
    more_findings: Annotated[StrictInt, Field(ge=0, le=MAX_MORE_FINDINGS)] = 0


def capped(parsed: ChoreResult, limit: int) -> ChoreResult:
    """Return `parsed` with at most `limit` findings: its first ones, the rest counted in `more_findings`.

    The chore is asked to list the most important first, so the ones kept are those it would keep.

    Returns:
        `parsed` itself when it is within `limit`, else a copy cut to it.
    """
    extra = len(parsed.findings) - limit
    if extra <= 0:
        return parsed
    return parsed.model_copy(
        update={
            "findings": parsed.findings[:limit],
            "more_findings": min(parsed.more_findings + extra, MAX_MORE_FINDINGS),
        }
    )


def parse(stdout: str) -> ChoreResult | None:
    """Parse `stdout`'s result line (DESIGN §13) as a chore's result. None if it is missing or invalid.

    Returns:
        The validated result, or None when no line starts with `{` or the last one does not validate.
    """
    return contract.last_line(ChoreResult, stdout)


def stored(result_json: object) -> ChoreResult | None:
    """Read a result the journal stored, or None if there is none (a run that ended without a valid result).

    Returns:
        The validated result, or None when `result_json` is not a non-empty string or does not validate.
    """
    return contract.stored(ChoreResult, result_json)


CONTRACT = (
    '{"status":"ok|failed","summary":"a paragraph, line breaks sparingly",'
    '"findings":[{"id":"stable/id","title":"one line","detail":"a paragraph","link":"https://..."}],"more_findings":0}'
)
