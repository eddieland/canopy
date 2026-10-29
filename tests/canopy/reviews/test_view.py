"""The state block's `reviews` cut to the PRs the overseer may act on (DESIGN §21, #1528)."""

from canopy.reviews import view
from canopy.reviews.view import RequestedPR, ReviewedPR, ReviewsSection

API = "https://github.com/acme/api/pull"


def reviewed(number: int, ticket: str | None) -> ReviewedPR:
    """A PR reviewed lately, for `ticket` or for none."""
    return {
        "url": f"{API}/{number}",
        "ticket": ticket,
        "review_runs": 1,
        "latest": {
            "run_id": number,
            "sha": "a" * 40,
            "status": "done",
            "verdict": "clean",
            "impact": "low",
            "findings": [],
            "dismissed_findings": 0,
            "held_findings": 0,
            "number": number,
        },
    }


def section(*prs: ReviewedPR) -> ReviewsSection:
    """A `reviews` section holding `prs`, newest first."""
    return {
        "agent_prs": True,
        "query": "is:pr",
        "low_impact": False,
        "limits": {
            "max_reviews": 1,
            "max_reviews_per_day": 20,
            "max_reviews_per_pr": 3,
            "settle_minutes": 0,
            "started_last_24h": 0,
        },
        "running": [],
        "settling": [],
        "prs": list(prs),
        "requests": [],
    }


# A listed ticket's PR; a done ticket's; a unit's PR reviewed with no ticket; a coworker's PR the query found; and one
# it no longer finds.
REVIEWED = section(
    reviewed(1, "PROJ-1"),
    reviewed(2, "PROJ-2"),
    reviewed(3, None),
    reviewed(4, None),
    reviewed(5, None),
)


def urls(scoped: ReviewsSection) -> list[str]:
    """The URLs of the PRs `scoped` keeps, in its order."""
    return [pr["url"] for pr in scoped["prs"]]


def test_the_prs_kept_are_the_listed_tickets_and_those_the_fresh_query_found() -> None:
    scoped = view.scoped(REVIEWED, tickets={"PROJ-1"}, prs={f"{API}/3"}, found={f"{API}/4"})
    assert urls(scoped) == [f"{API}/1", f"{API}/3", f"{API}/4"]
    assert {k: v for k, v in scoped.items() if k != "prs"} == {k: v for k, v in REVIEWED.items() if k != "prs"}


def test_while_the_overseer_runs_the_query_itself_every_pr_of_no_ticket_is_kept() -> None:
    scoped = view.scoped(REVIEWED, tickets={"PROJ-1"}, prs=set(), found=None)
    assert urls(scoped) == [f"{API}/1", f"{API}/3", f"{API}/4", f"{API}/5"]


def test_with_no_query_a_pr_of_no_ticket_and_no_unit_is_left_out_unless_the_operator_asked() -> None:
    assert urls(view.scoped(REVIEWED, tickets=set(), prs=set(), found=frozenset())) == []
    request: RequestedPR = {
        "url": f"{API}/5",
        "requested_at": "2026-10-28T09:00:00.000Z",
        "review_runs": 1,
        "latest": None,
    }
    requested: ReviewsSection = {**REVIEWED, "requests": [request]}
    assert urls(view.scoped(requested, tickets=set(), prs=set(), found=frozenset())) == [f"{API}/5"]
