"""A review's result contract (DESIGN §21), and a revision's (§34): the agent's last line, validated before use.

The reviewer and the reviser read the most hostile text the loop meets, so everything they report is untrusted and
bounded. A result that does not validate is `unknown`.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictStr, model_validator

from canopy.core import contract
from canopy.core.contract import bounded, one_line

MAX_SUMMARY: Final = 2000
MAX_TITLE: Final = 200
MAX_LOCATION: Final = 300
MAX_DETAIL: Final = 1000
MAX_FINDINGS: Final = 20
#: A revised version's bounds: a draft's text and comments, as `replies` bounds them (it imports too much for here).
MAX_REVISED_TEXT: Final = 4000
MAX_REVISED_COMMENTS: Final = 30


def _finding_number(value: object) -> object:
    """Return `value` if it is a finding's number, else None: a malformed `rebuts` drops, never the finding with it."""
    is_number = isinstance(value, int) and not isinstance(value, bool) and 0 < value <= MAX_FINDINGS
    return value if is_number else None


class Finding(BaseModel):
    """One defect the reviewer verified against the code."""

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    severity: Literal["blocking", "major", "minor"]
    title: Annotated[StrictStr, one_line, bounded(MAX_TITLE)]
    location: Annotated[StrictStr, one_line, bounded(MAX_LOCATION)] = ""
    # What is wrong and why, for the worker that fixes it: the review is posted nowhere else (DESIGN §21).
    detail: Annotated[StrictStr, bounded(MAX_DETAIL)] = ""
    #: The number, in the previous review, of a finding the worker declined that this one rebuts: the reviewer's claim,
    #: which the harness holds the finding for the operator on only when the worker did decline it (DESIGN §21).
    rebuts: Annotated[int | None, BeforeValidator(_finding_number)] = None


class ReviewResult(BaseModel):
    """`done` means the review was read through; `failed` that the reviewer could not review.

    The result is the whole review: it lives in the journal and is posted nowhere (D114).
    """

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    status: Literal["done", "failed"]
    verdict: Literal["clean", "findings"] | None = None
    impact: Literal["low", "normal", "high"] | None = None
    #: The review for canopy's operator: what the change does, and where its risk is.
    summary: Annotated[StrictStr, bounded(MAX_SUMMARY)] = ""
    #: What the reviewer would say to the PR's author beyond the findings, often nothing: a draft's body (DESIGN §34).
    body: Annotated[StrictStr, bounded(MAX_REVISED_TEXT)] = ""
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


class RevisedComment(BaseModel):
    """One comment of a revised version: where it goes, and its text."""

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    #: `path:line` on the commit's side of the diff the review kept; a comment elsewhere goes in the body under it.
    location: Annotated[StrictStr, one_line, bounded(MAX_LOCATION)]
    text: Annotated[StrictStr, bounded(MAX_REVISED_TEXT)]


class RevisionResult(BaseModel):
    """A revision's result (DESIGN §34): the new version of a review's draft if `done`; if `failed`, why, in `body`.

    It is what would post, written from the PR's text and the operator's notes: untrusted until the operator publishes.
    """

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    status: Literal["done", "failed"]
    body: Annotated[StrictStr, bounded(MAX_REVISED_TEXT)] = ""
    comments: Annotated[list[RevisedComment], Field(max_length=MAX_REVISED_COMMENTS)] = []


def parse_revision(stdout: str) -> RevisionResult | None:
    """Parse `stdout`'s result line (DESIGN §13) as a revision's result. None if it is missing or invalid.

    Returns:
        The validated result, or None if `stdout` has no result line or its last one does not validate.
    """
    return contract.last_line(RevisionResult, stdout)


CONTRACT: Final = (
    '{"status":"done|failed","verdict":"clean|findings","impact":"low|normal|high",'
    '"summary":"a paragraph, line breaks sparingly",'
    '"body":"what you would tell the PR\'s author beyond the findings, or nothing",'
    '"pr_title":"the PR\'s title as it stands",'
    '"findings":[{"severity":"blocking|major|minor","title":"one line","location":"path:line",'
    '"detail":"what is wrong and why","rebuts":null}]}'
)
REVISION_CONTRACT: Final = (
    '{"status":"done|failed","body":"the review\'s body, or why you could not revise",'
    '"comments":[{"location":"path:line","text":"the comment"}]}'
)
