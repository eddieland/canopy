"""The API's types for the CI report (DESIGN §11): which checks fail, what fixing them cost, and whether kicks worked.

Read from the check runs a `vcs` source observed, the runs that fixed CI, and the flaky kicks. Built on `schema.Model`,
as every API type is (schema/__init__.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from canopy.serve.schema import Model
from canopy.serve.schema.health import HealthRefusal

type CiVerdict = Annotated[
    Literal["green", "red", "neither"],
    Field(
        description="How a check run counts: `red` for `failure`, `error`, `timed_out`, or `startup_failure`, `green` "
        "for `success`, and `neither` for the rest (`cancelled`, `skipped`, `neutral`, `stale`, `action_required`).",
    ),
]


class CiCheck(Model):
    """One check's runs observed in the window, by its name across every PR."""

    name: str
    """The check's name, as its host names it."""
    runs: int
    """Its runs a source observed completed in the window."""
    red: int
    """Of those, the red ones."""
    green: int
    """Of those, the green ones; the rest counted as neither."""
    followed: int
    """Its red runs that a later run of it on a new head of the same PR followed."""
    passed: int
    """Of those, the ones whose next run on the new head was green."""
    reruns: int
    """Its runs in the window on a head of a PR where a run of it was red before: reruns with no change to the code."""
    reruns_green: int
    """Of those, the green ones: a check that passed on a head it had failed on, flaky without anyone's say-so."""


class CiDay(Model):
    """One local day of the window: its red check runs, by the chart's series, and the PR heads first checked on it."""

    day: str
    """The day, `YYYY-MM-DD`, in the local time of the machine canopy runs on."""
    start: datetime
    """When it starts: its local midnight, so a page can write it in its own zone."""
    red: list[int]
    """Each series' red runs, in `CiReport.series` order."""
    heads: int
    """The PR heads whose first check run was observed on the day, counted as `CiReport.heads` counts them."""
    green_first: int
    """Of those, the heads whose first run of every check was not red."""


class CiFixedCheck(Model):
    """A check a fix found red on its PR's head, and how its first run on the head after it ended."""

    pr_url: str
    """The PR it ran on."""
    name: str
    """The check's name."""
    next: CiVerdict | None = None
    """How its first run on the next head ended; None while no source has observed one."""


class CiFix(Model):
    """A `resume` for `ci`, or a retired `fix-ci`, that started in the window."""

    run_id: int
    """The run."""
    ticket_key: str
    """Its ticket."""
    kind: str
    """Its kind: `resume`, or `fix-ci` for a run from before a `resume` fixed CI."""
    status: str
    """How it ended, or `running`."""
    started_at: datetime
    """When it started."""
    cost_usd: float | None = None
    """What it cost, in US dollars; None when it reported none."""
    checks: list[CiFixedCheck]
    """The checks red on its PRs' heads when it started; empty when no source had observed one."""
    hours_to_green: float | None = None
    """The longest time to green of its PRs that went red, as `CiPullRequest.hours_to_green` measures it; None while
    one of them is still red, or none went red."""


class CiPullRequest(Model):
    """A PR with a check run observed in the window, and how long it stayed red."""

    url: str
    """The PR."""
    ticket_key: str | None = None
    """The ticket that owns it: its unit's, else the ticket of the first run that named it; None for a PR no run
    named."""
    phase: str | None = None
    """Its unit's phase (DESIGN §7); None for a PR no unit of the loop's has."""
    red_at: datetime | None = None
    """When a source first observed a red run of a check on it; None when none was red."""
    green_at: datetime | None = None
    """When its first head from the red one on went green: no check's last red or green run on it red, and one green,
    at the observation of the last of those; None while none has, or when it was never red."""
    hours_to_green: float | None = None
    """From `red_at` to `green_at`, in hours; None without both. Approximate: each time is when a source saw a run
    completed, not when it finished, and a head whose other checks still run reads green until one is seen red."""


class CiKick(Model):
    """A flaky kick made in the window: a branch rebased and pushed so its checks ran again."""

    run_id: int
    """The `resume` whose worker judged the check flaky."""
    repo: str
    """The workspace repository it kicked."""
    branch: str
    """The branch it kicked."""
    pr_url: str | None = None
    """The PR its run named, else the one a source observed at its heads; None with neither."""
    kicked_at: datetime
    """When it was made."""
    kick: int
    """Which of its head's kicks it was, from 1, as `trust.max_flaky_kicks` counts them."""
    red_before: list[str]
    """The checks red on the head it replaced."""
    still_red: list[str]
    """Of those, the ones whose first run on the head it pushed was red again."""
    checked: bool
    """Whether a source has observed a run of any of them on the head it pushed."""


class CiKickedPullRequest(Model):
    """A PR the window's kicks reran the checks of."""

    url: str
    """The PR."""
    ticket_key: str | None = None
    """The ticket that owns it: its unit's, else the one its runs or a kick's run named."""
    phase: str | None = None
    """Its unit's phase (DESIGN §7); None for a PR no unit of the loop's has."""
    kicks: int
    """Its kicks in the window."""
    most: int
    """The most of them one head of work had, against `trust.max_flaky_kicks`."""
    still_red: int
    """Its kicks whose check came back red."""


class CiReport(Model):
    """Which checks failed in the window, what fixing them cost, and whether the flaky kicks worked."""

    days: int
    """How many local days the window holds, today's so far included."""
    since: datetime
    """When the window starts: local midnight on its first day."""
    until: datetime
    """When it ends: local midnight after today."""
    heads: int
    """The PR heads first checked in the window that had a red or a green first run of a check."""
    green_first: int
    """Of those, the heads whose first run of every check was not red."""
    checks: list[CiCheck]
    """The worst first: the most red runs, then the highest share of red among red and green."""
    series: list[str | None]
    """The check names the red-by-day chart names apart, the most often red first, then None for every other check
    when any other was red."""
    per_day: list[CiDay]
    """Every day of the window, oldest first."""
    fixes: list[CiFix]
    """The newest first."""
    kicks: list[CiKick]
    """The newest first."""
    kicked_pull_requests: list[CiKickedPullRequest]
    """The most kicked first."""
    pull_requests: list[CiPullRequest]
    """Still red first, the oldest red first; then the longest time to green first; then those never red."""
    median_hours_to_green: float | None = None
    """The median of `pull_requests`' hours to green, over those that went green; None with none."""
    max_flaky_kicks: int
    """`trust.max_flaky_kicks`: how many kicks a head of work gets; 0 when canopy kicks none."""
    cooldown: HealthRefusal | None = None
    """What the `cooldown` guard refused in the window, as the health report counts it; None when it refused nothing."""
