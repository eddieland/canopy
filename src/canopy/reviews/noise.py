"""How much of what canopy's reviewer finds the operator dismisses, and why (DESIGN §21): `canopy review noise`.

Each `done` review's findings are counted by severity, by the persona the review ran in, and by the models its session
named, beside the operator's dismissals of them by reason. A `wrong` dismissal is the reviewer's noise; an
`intentional` or `not_worth_it` one is a finding that held and was not acted on. A dismissal from before canopy asked
why counts as `unrecorded`. Read from the journal only.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from canopy.core import review_result as result
from canopy.core import review_runs, run_models
from canopy.core.vocab import DismissalReason, ReviewRunStatus

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


@dataclass
class Tally:
    """The findings of one group, and what the operator dismissed of them."""

    #: What the group is: a severity, a persona's name, or the models that served its reviews.
    key: str
    findings: int = 0
    #: The dismissed findings by reason, `unrecorded` among them; a reason none was dismissed for is absent.
    dismissed: Counter[str] = field(default_factory=Counter)

    def rate(self, reason: DismissalReason) -> float:
        """Return the share of the group's findings the operator dismissed for `reason`, from 0 to 1."""
        return self.dismissed[reason] / self.findings if self.findings else 0.0


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
            reason, and `rates` by reason.
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
                        "rates": {str(r): round(t.rate(r), 4) for r in DismissalReason},
                    }
                    for t in tallies
                ]
                for dimension, tallies in self.groups.items()
            },
        }


def tally(conn: sqlite3.Connection, since: str) -> Noise:
    """Count the findings of every `done` review started at or after `since`, and the operator's dismissals of them.

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
    return Noise(
        since=since,
        reviews=len(runs),
        groups={d: sorted(g.values(), key=lambda t: (-t.findings, t.key)) for d, g in groups.items()},
    )


def lines(noise: Noise) -> list[str]:
    """Return the tallies as text: a table per dimension, each group's findings, dismissals, and `wrong` rate.

    Returns:
        The lines to print; one saying so when the reviews found nothing.
    """
    head = f"{noise.reviews} done reviews since {noise.since}"
    if not any(noise.groups.values()):
        return [f"{head}: no findings."]
    columns = [*(str(r) for r in DismissalReason), UNRECORDED]
    found = [f"{head}. A `wrong` dismissal is the reviewer's noise."]
    for dimension, tallies in noise.groups.items():
        width = max(len(dimension), *(len(t.key) for t in tallies))
        found += ["", f"{dimension:<{width}}  findings  {'  '.join(columns)}  wrong rate"]
        for t in tallies:
            counts = "  ".join(f"{t.dismissed[c]:>{len(c)}}" for c in columns)
            found.append(f"{t.key:<{width}}  {t.findings:>8}  {counts}  {t.rate(DismissalReason.WRONG):>10.0%}")
    return found
