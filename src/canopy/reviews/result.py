"""A review's result contract (DESIGN §21): the last line of the reviewer's stdout, validated before anything reads it.

The reviewer reads the most hostile text the loop meets, so everything it reports is untrusted and bounded. A result
that does not validate is `unknown`.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from canopy.core import contract
from canopy.core.contract import bounded, one_line

MAX_SUMMARY = 2000
MAX_TITLE = 200
MAX_LOCATION = 300
MAX_FINDINGS = 20
MAX_URL = 500


class Finding(BaseModel):
    """One defect the reviewer verified against the code."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    severity: Literal["blocking", "major", "minor"]
    title: Annotated[StrictStr, one_line, bounded(MAX_TITLE)]
    location: Annotated[StrictStr, one_line, bounded(MAX_LOCATION)] = ""


class ReviewResult(BaseModel):
    """`done` means the review was read through and its comment posted; `failed` that the reviewer could not review."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    status: Literal["done", "failed"]
    verdict: Literal["clean", "findings"] | None = None
    impact: Literal["low", "normal", "high"] | None = None
    comment: Annotated[StrictStr, contract.url(MAX_URL)] | None = None
    summary: Annotated[StrictStr, bounded(MAX_SUMMARY)] = ""
    findings: Annotated[list[Finding], Field(max_length=MAX_FINDINGS)] = []

    @model_validator(mode="after")
    def _verdict_matches(self) -> Self:
        if self.status == "done" and (self.verdict is None or self.impact is None):
            raise ValueError("a done review has a verdict and an impact")
        if self.verdict is not None and (self.verdict == "findings") != bool(self.findings):
            raise ValueError("verdict is findings exactly when findings is not empty")
        return self


def parse(stdout: str) -> ReviewResult | None:
    """Parse the last non-empty line of `stdout` as a review's result. None if it is missing or invalid."""
    return contract.last_line(ReviewResult, stdout)


def stored(result_json: object) -> ReviewResult | None:
    """Read a result the journal stored, or None if there is none."""
    return contract.stored(ReviewResult, result_json)


CONTRACT = (
    '{"status":"done|failed","verdict":"clean|findings","impact":"low|normal|high","comment":"https://...",'
    '"summary":"one paragraph","findings":[{"severity":"blocking|major|minor","title":"one line",'
    '"location":"path:line"}]}'
)
