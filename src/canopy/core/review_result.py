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
MAX_DETAIL = 1000
MAX_FINDINGS = 20


class Finding(BaseModel):
    """One defect the reviewer verified against the code."""

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    severity: Literal["blocking", "major", "minor"]
    title: Annotated[StrictStr, one_line, bounded(MAX_TITLE)]
    location: Annotated[StrictStr, one_line, bounded(MAX_LOCATION)] = ""
    # What is wrong and why, for the worker that fixes it: the review is posted nowhere else (DESIGN §21).
    detail: Annotated[StrictStr, bounded(MAX_DETAIL)] = ""


class ReviewResult(BaseModel):
    """`done` means the review was read through; `failed` that the reviewer could not review.

    The result is the whole review: it lives in the journal and is posted nowhere (D114).
    """

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    status: Literal["done", "failed"]
    verdict: Literal["clean", "findings"] | None = None
    impact: Literal["low", "normal", "high"] | None = None
    summary: Annotated[StrictStr, bounded(MAX_SUMMARY)] = ""
    # The PR's title as the reviewer read it, for display: it need not be its ticket's, and a PR canopy only reviews has
    # no other (DESIGN §21).
    pr_title: Annotated[StrictStr, one_line, bounded(contract.MAX_PR_TITLE)] | None = None
    findings: Annotated[list[Finding], Field(max_length=MAX_FINDINGS)] = []

    @model_validator(mode="after")
    def _verdict_matches(self) -> Self:
        if self.status == "done" and (self.verdict is None or self.impact is None):
            raise ValueError("a done review has a verdict and an impact")
        if self.verdict is not None and (self.verdict == "findings") != bool(self.findings):
            raise ValueError("verdict is findings exactly when findings is not empty")
        return self


def parse(stdout: str) -> ReviewResult | None:
    """Parse `stdout`'s result line (DESIGN §13) as a review's result. None if it is missing or invalid.

    Returns:
        The validated result, or None if `stdout` has no result line or its last one does not validate.
    """
    return contract.last_line(ReviewResult, stdout)


def stored(result_json: object) -> ReviewResult | None:
    """Read a result the journal stored, or None if there is none.

    Returns:
        The validated result, or None if the run stored none or what it stored does not validate.
    """
    return contract.stored(ReviewResult, result_json)


CONTRACT = (
    '{"status":"done|failed","verdict":"clean|findings","impact":"low|normal|high","summary":"one paragraph",'
    '"pr_title":"the PR\'s title as it stands",'
    '"findings":[{"severity":"blocking|major|minor","title":"one line","location":"path:line",'
    '"detail":"what is wrong and why"}]}'
)
