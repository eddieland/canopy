"""How much of what canopy's reviewer finds the operator dismisses, and why (DESIGN §21): `canopy review noise`.

Each `done` review's findings are counted by severity, by the persona the review ran in, and by the models its session
named, beside what became of each: the operator's dismissal by reason, or else the latest answer a worker gave it,
`fixed` or `declined`, as the next review reads it. A `wrong` dismissal is the reviewer's noise; an `intentional` or
`not_worth_it` one is a finding that held and was not acted on. A dismissal from before canopy asked why counts as
`unrecorded`. The operator's dismissal wins over a worker's answer, since it is the operator's word on the finding: a
finding both dismissed and answered counts as dismissed alone. One neither dismissed nor answered counts in the total
only. Apart from those, a finding the harness held as a rebuttal of a worker's decline counts as one, whether the
operator has released it or not. Read from the journal only.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, assert_never

from canopy.core import review_answers, review_runs, run_models
from canopy.core import review_result as result
from canopy.core.vocab import DismissalReason, FindingAnswer, HoldKind, ReviewRunStatus

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping, Sequence

#: What the findings are grouped by.
type Dimension = Literal["severity", "persona", "model"]

#: Each dimension, in the order the tables print.
DIMENSIONS: tuple[Dimension, ...] = ("severity", "persona", "model")
#: The group of a review run in no persona: the default reviewer, or a review from before canopy recorded one.
NO_PERSONA = "(no persona)"
#: The group of a review run whose session named no model, or has not been read yet.
NO_MODEL = "(no model read)"
#: What a dismissal from before canopy asked why is counted as.
UNRECORDED = "unrecorded"
#: What the text's columns mean, after its first line's count of reviews.
LEGEND = (
    "A `wrong` dismissal is the reviewer's noise; `fixed` and `declined` are workers' answers to the findings not "
    "dismissed, and a rebuttal answers a decline."
)


@dataclass
class Tally:
    """The findings of one group, what the operator dismissed of them, and what workers answered of the rest."""

    #: What the group is: a severity, a persona's name, or the models that served its reviews.
    key: str
    findings: int = 0
    #: The dismissed findings by reason, `unrecorded` among them; a reason none was dismissed for is absent.
    dismissed: Counter[str] = field(default_factory=Counter)
    #: The findings not dismissed, by the latest answer a worker gave them; an answer none was given is absent.
    answered: Counter[str] = field(default_factory=Counter)
    #: The findings the harness held as a rebuttal of a worker's decline, released since or not.
    rebuttals: int = 0

    def rate(self, outcome: DismissalReason | FindingAnswer) -> float:
        """Return the share of the group's findings dismissed for `outcome`, or answered so, from 0 to 1."""
        match outcome:
            case DismissalReason():
                count = self.dismissed[outcome]
            case FindingAnswer():
                count = self.answered[outcome]
            case _:
                assert_never(outcome)
        return count / self.findings if self.findings else 0.0


@dataclass(frozen=True)
class Noise:
    """The findings of the `done` reviews started since a time, in a tally per group of each dimension."""

    since: str
    reviews: int
    #: Each dimension's groups, the most findings first.
    groups: Mapping[Dimension, Sequence[Tally]]

    def as_json(self) -> dict[str, object]:
        """Return the tallies as one JSON object, each rate the share of its group's findings.

        Returns:
            `since`, `reviews`, and for each dimension a list of its groups' `key`, `findings`, `dismissed` by
            reason, `answered` by answer, `rebuttals`, and `rates` by reason and answer.
        """
        return {
            "since": self.since,
            "reviews": self.reviews,
            **{
                dimension: [
                    {
                        "key": t.key,
                        "findings": t.findings,
                        "dismissed": dict(t.dismissed),
                        "answered": dict(t.answered),
                        "rebuttals": t.rebuttals,
                        "rates": {str(o): round(t.rate(o), 4) for o in (*DismissalReason, *FindingAnswer)},
                    }
                    for t in tallies
                ]
                for dimension, tallies in self.groups.items()
            },
        }


def tally(conn: sqlite3.Connection, since: str) -> Noise:
    """Count the findings of every `done` review started at or after `since`, and what became of each.

    Returns:
        The tallies by severity, persona, and model.
    """
    runs = [r for r in review_runs.review_runs_since(conn, since) if r.status is ReviewRunStatus.DONE]
    models = run_models.of_runs(conn, "review_runs", [r.id for r in runs])
    groups: dict[Dimension, dict[str, Tally]] = {d: {} for d in DIMENSIONS}
    for run in runs:
        stored = result.stored(run.result_json)
        if stored is None:
            continue
        dismissed = review_runs.review_dismissals(conn, run.id)
        answers = review_answers.latest(conn, run.id)
        holds = review_runs.held(conn, run.id, released=True)
        rebuttals = {n for n, h in holds.items() if h.kind is HoldKind.REBUTTAL}
        served = "+".join(sorted(m.model for m in models[run.id])) or NO_MODEL
        for number, finding in enumerate(stored.findings, 1):
            keys: dict[Dimension, str] = {
                "severity": finding.severity,
                "persona": run.persona or NO_PERSONA,
                "model": served,
            }
            for dimension, key in keys.items():
                group = groups[dimension].setdefault(key, Tally(key))
                group.findings += 1
                if number in dismissed:
                    group.dismissed[str(dismissed[number] or UNRECORDED)] += 1
                elif number in answers:
                    group.answered[str(answers[number].answer)] += 1
                if number in rebuttals:
                    group.rebuttals += 1
    return Noise(
        since=since,
        reviews=len(runs),
        groups={d: sorted(g.values(), key=lambda t: (-t.findings, t.key)) for d, g in groups.items()},
    )


def lines(noise: Noise) -> list[str]:
    """Return the tallies as text: a table per dimension, each group's findings, their outcomes, and `wrong` rate.

    Returns:
        The lines to print; one saying so when the reviews found nothing.
    """
    head = f"{noise.reviews} done reviews since {noise.since}"
    if not any(noise.groups.values()):
        return [f"{head}: no findings."]
    reasons = [*(str(r) for r in DismissalReason), UNRECORDED]
    answers = [str(a) for a in FindingAnswer]
    found = [f"{head}. {LEGEND}"]
    for dimension, tallies in noise.groups.items():
        width = max(len(dimension), *(len(t.key) for t in tallies))
        found += ["", f"{dimension:<{width}}  findings  {'  '.join([*reasons, *answers])}  rebuttals  wrong rate"]
        for t in tallies:
            counts = [f"{t.dismissed[c]:>{len(c)}}" for c in reasons] + [f"{t.answered[c]:>{len(c)}}" for c in answers]
            rate = f"{t.rate(DismissalReason.WRONG):>10.0%}"
            found.append(f"{t.key:<{width}}  {t.findings:>8}  {'  '.join(counts)}  {t.rebuttals:>9}  {rate}")
    return found
