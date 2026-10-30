"""What CI did on the PRs canopy observed (DESIGN §11), for the web UI's CI page.

Reads only. Over the same window as `canopy spend` and `canopy health` (whole local days, today's so far included),
by when a source first observed each check run completed: how many PR heads were green the first time their checks ran;
each check's runs, red runs, and how often its next run on a new head passed; each day's red runs by check; each
`resume` for `ci`, a retired `fix-ci` among them, with whether the next run of each check it found red, on the head
after it started, passed; and each flaky kick, with whether the check came back red.

Red is `failure`, `error`, `timed_out`, or `startup_failure`; green is `success`; the rest (`cancelled`, `skipped`,
`neutral`, `stale`, `action_required`) count as neither. Only the check runs a `vcs` source observed are kept
(`observed_check_runs`, from M36 on), so only the PRs canopy observed are here, and a commit status, which has no run,
has no history and is not counted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from canopy.core import contract, db, records, spend, tracked_prs
from canopy.core.vocab import CheckConclusion, ResumeReason, RunKind

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import datetime

    from canopy.core.vocab import Phase, RunStatus

#: The conclusions that count a check run red. `success` alone counts it green; every other counts as neither.
RED = frozenset(
    {CheckConclusion.FAILURE, CheckConclusion.ERROR, CheckConclusion.TIMED_OUT, CheckConclusion.STARTUP_FAILURE},
)
#: How many check names the red-by-day chart names apart, the most often red first; the rest are one series.
TOP_CHECKS = 4

#: How a check run ended, as the page counts it.
type Verdict = Literal["green", "red", "neither"]


@dataclass(frozen=True)
class Check:
    """One check's runs observed in the window, by its name across every PR."""

    name: str
    runs: int
    red: int
    green: int
    #: Its red runs that a later run of it on a new head of the same PR followed.
    followed: int
    #: Of those, the ones whose next run on the new head was green.
    passed: int


@dataclass(frozen=True)
class Day:
    """One local day of the window: its red check runs, by the chart's series."""

    #: The day, `YYYY-MM-DD`, as `spend.local_day` names it.
    day: str
    #: When it starts: its local midnight, a journal time.
    start: str
    #: Each series' red runs, in `Ci.series` order.
    red: Sequence[int]


@dataclass(frozen=True)
class FixedCheck:
    """A check a fix found red on its PR's head, and how its first run on the head after it ended."""

    pr_url: str
    name: str
    #: How its first run on the next head ended; None while no source has observed one.
    next: Verdict | None


@dataclass(frozen=True)
class Fix:
    """A `resume` for `ci`, or a retired `fix-ci`, that started in the window, newest first."""

    run_id: int
    ticket: str
    kind: RunKind
    status: RunStatus
    started_at: str
    cost_usd: float | None
    #: The checks red on its PRs' heads when it started; none when no source had observed one.
    checks: Sequence[FixedCheck]


@dataclass(frozen=True)
class Kick:
    """A flaky kick made in the window, newest first: a branch rebased and pushed so its checks ran again."""

    run_id: int
    repo: str
    branch: str
    #: The PR its run named for the repository, else the one a source observed at its heads; None with neither.
    pr_url: str | None
    kicked_at: str
    #: Which of its head's kicks it was, from 1, as `trust.max_flaky_kicks` counts them.
    kick: int
    #: The checks red on the head it replaced, by name.
    red_before: Sequence[str]
    #: Of those, the ones whose first run on the head it pushed was red again.
    still_red: Sequence[str]
    #: Whether a source has observed a run of any of them on the head it pushed.
    checked: bool


@dataclass(frozen=True)
class KickedPr:
    """A PR the window's kicks reran the checks of, the most kicked first."""

    url: str
    #: The ticket that owns it (`tracked_prs`), else the ticket of a kick's run.
    ticket: str | None
    phase: Phase | None
    kicks: int
    #: The most of its kicks one head of work had, to hold against `trust.max_flaky_kicks`.
    most: int
    #: Its kicks whose check came back red.
    still_red: int


@dataclass(frozen=True)
class Ci:
    """What CI did in the window `[since, until)`, `spend.window`'s, on the PRs canopy observed."""

    since: str
    until: str
    days: int
    #: The PR heads whose first check run was observed in the window and had a red or a green first run of a check.
    heads: int
    #: Of those, the heads whose first run of every check was not red.
    green_first: int
    #: The worst first: the most red runs, then the highest share of red among red and green, then by name.
    checks: Sequence[Check]
    #: The check names the chart names apart, the most often red first, then None for the rest when any was red.
    series: Sequence[str | None]
    per_day: Sequence[Day]
    fixes: Sequence[Fix]
    kicks: Sequence[Kick]
    kicked_prs: Sequence[KickedPr]


def report(conn: sqlite3.Connection, now: datetime, days: int) -> Ci:
    """What CI did over the last `days` local days, today's so far included, on the PRs canopy observed.

    Returns:
        The report; a window with no check run in it has no heads, checks, or series, and each day at nothing.
    """
    start, end = spend.window(now, days)
    since, until = db.format_time(start), db.format_time(end)
    starts = spend.day_starts(start, days)
    with db.read_snapshot(conn):
        tracked = tracked_prs.tracked(conn, since, until)
        fixes = _fix_runs(conn, since, until)
        kicks = records.select(records.FlakyKick).where("kicked_at < ?", until).order_by("kicked_at, run_id").all(conn)
        fix_prs = {r.id: _prs_of(r, tracked) for r in fixes}
        kick_runs = _runs(conn, {k.run_id for k in kicks if k.kicked_at >= since})
        runs = _check_runs(
            conn,
            since,
            until,
            prs={url for urls in fix_prs.values() for url in urls},
            heads={h for k in kicks for h in (k.from_head, k.to_head)},
        )
    by_pr: dict[str, list[records.ObservedCheckRun]] = {}
    for run in runs:
        by_pr.setdefault(run.pr_url, []).append(run)
    in_window = [r for r in runs if since <= r.observed_at < until]
    heads, green_first = _first_heads(by_pr, since, until)
    series = _series(in_window)
    window_kicks = [k for k in kicks if k.kicked_at >= since]
    found_kicks = [_kick(k, kicks, kick_runs, runs) for k in reversed(window_kicks)]
    return Ci(
        since=since,
        until=until,
        days=days,
        heads=heads,
        green_first=green_first,
        checks=_checks(in_window, by_pr),
        series=series,
        per_day=_per_day(in_window, series, starts),
        fixes=[_fix(r, fix_prs[r.id], by_pr) for r in fixes],
        kicks=found_kicks,
        kicked_prs=_kicked_prs(found_kicks, tracked, kick_runs),
    )


# How the page counts a check run: `red` for one of `RED`, `green` for `success`, and `neither` for the rest.
def _verdict(conclusion: CheckConclusion) -> Verdict:
    if conclusion in RED:
        return "red"
    return "green" if conclusion is CheckConclusion.SUCCESS else "neither"


# Each `resume` for `ci` that started in the window, and each retired `fix-ci`, which counts as one (DESIGN §8), the
# newest first.
def _fix_runs(conn: sqlite3.Connection, since: str, until: str) -> list[records.Run]:
    query = (
        records.select(records.Run)
        .where("runs.started_at >= ? AND runs.started_at < ?", since, until)
        .where(
            "(runs.kind = ? OR (runs.kind = ? AND runs.id IN (SELECT run_id FROM run_reasons WHERE reason = ?)))",
            RunKind.FIX_CI,
            RunKind.RESUME,
            ResumeReason.CI,
        )
        .order_by("runs.started_at DESC, runs.id DESC")
    )
    return query.all(conn)


def _runs(conn: sqlite3.Connection, ids: Iterable[int]) -> dict[int, records.Run]:
    found = records.select(records.Run).where("runs.id IN (SELECT value FROM json_each(?))", json.dumps(sorted(ids)))
    return {r.id: r for r in found.all(conn)}


# The PRs a fix worked on: those its result named, else those its ticket's runs named, as the tracked PRs list them. A
# run that failed before it named a PR names none, so its ticket's are the ones it was dispatched for.
def _prs_of(run: records.Run, tracked: Mapping[str, tracked_prs.TrackedPr]) -> list[str]:
    named = contract.stored_prs(contract.stored_object(run.result_json))
    return list(dict.fromkeys(named)) or [url for url, pr in tracked.items() if pr.ticket == run.ticket_key]


# The check runs the report reads, oldest first: every run of each PR with a run observed in the window or a fix's,
# for the runs before and after the window's that judge them, and every run at a kick's heads.
def _check_runs(
    conn: sqlite3.Connection,
    since: str,
    until: str,
    *,
    prs: Iterable[str],
    heads: Iterable[str],
) -> list[records.ObservedCheckRun]:
    query = (
        records.select(records.ObservedCheckRun)
        .where(
            "(pr_url IN (SELECT pr_url FROM observed_check_runs WHERE observed_at >= ? AND observed_at < ?) "
            "OR pr_url IN (SELECT value FROM json_each(?)) OR head_sha IN (SELECT value FROM json_each(?)))",
            since,
            until,
            json.dumps(sorted(set(prs))),
            json.dumps(sorted(set(heads))),
        )
        .order_by("observed_at, run_id")
    )
    return query.all(conn)


# How many PR heads first checked in the window had a red or green first run of a check, and how many of those had no
# red one: each check's first run on the head is what the head's push got, before any rerun.
def _first_heads(
    by_pr: Mapping[str, Sequence[records.ObservedCheckRun]],
    since: str,
    until: str,
) -> tuple[int, int]:
    heads = green = 0
    for runs in by_pr.values():
        first_seen: dict[str, str] = {}
        first_runs: dict[str, dict[str, Verdict]] = {}
        for run in runs:
            first_seen.setdefault(run.head_sha, run.observed_at)
            first_runs.setdefault(run.head_sha, {}).setdefault(run.name, _verdict(run.conclusion))
        for head, seen in first_seen.items():
            verdicts = set(first_runs[head].values())
            if not since <= seen < until or verdicts == {"neither"}:
                continue
            heads += 1
            green += "red" not in verdicts
    return heads, green


# Each check's runs in the window, the worst first, with how often a red one's next run on a new head passed.
def _checks(
    in_window: Iterable[records.ObservedCheckRun],
    by_pr: Mapping[str, Sequence[records.ObservedCheckRun]],
) -> list[Check]:
    by_name: dict[str, list[records.ObservedCheckRun]] = {}
    for run in in_window:
        by_name.setdefault(run.name, []).append(run)
    found: list[Check] = []
    for name, runs in by_name.items():
        verdicts = [_verdict(r.conclusion) for r in runs]
        after = [_next_on_new_head(by_pr[r.pr_url], r) for r in runs if _verdict(r.conclusion) == "red"]
        followed = [r for r in after if r is not None]
        found.append(
            Check(
                name=name,
                runs=len(runs),
                red=verdicts.count("red"),
                green=verdicts.count("green"),
                followed=len(followed),
                passed=sum(1 for r in followed if _verdict(r.conclusion) == "green"),
            ),
        )
    return sorted(found, key=lambda c: (-c.red, -_share(c), c.name))


def _share(check: Check) -> float:
    judged = check.red + check.green
    return check.red / judged if judged else 0.0


# The first run of `run`'s check on its PR, observed after it, on a head other than its own.
def _next_on_new_head(
    runs: Iterable[records.ObservedCheckRun],
    run: records.ObservedCheckRun,
) -> records.ObservedCheckRun | None:
    later = (
        r
        for r in runs
        if r.name == run.name
        and r.head_sha != run.head_sha
        and (r.observed_at, r.run_id) > (run.observed_at, run.run_id)
    )
    return next(later, None)


# The chart's series: the `TOP_CHECKS` names most often red in the window, then None for the rest, if any was red.
def _series(in_window: Iterable[records.ObservedCheckRun]) -> list[str | None]:
    red: dict[str, int] = {}
    for run in in_window:
        if _verdict(run.conclusion) == "red":
            red[run.name] = red.get(run.name, 0) + 1
    ranked = sorted(red, key=lambda name: (-red[name], name))
    named: list[str | None] = list(ranked[:TOP_CHECKS])
    return [*named, None] if len(ranked) > TOP_CHECKS else named


def _per_day(
    in_window: Iterable[records.ObservedCheckRun],
    series: Sequence[str | None],
    starts: Mapping[str, str],
) -> list[Day]:
    other = series.index(None) if None in series else None
    red = {day: [0] * len(series) for day in starts}
    for run in in_window:
        day = red.get(spend.local_day(run.observed_at))
        if day is None or _verdict(run.conclusion) != "red":
            continue
        index = series.index(run.name) if run.name in series else other
        if index is not None:
            day[index] += 1
    return [Day(day=day, start=at, red=red[day]) for day, at in starts.items()]


# A fix's checks: on each of its PRs, the checks red on the head its PR had when it started, and how each one's first
# run on the next head, the first one a source observed after it started, ended.
def _fix(
    run: records.Run,
    prs: Iterable[str],
    by_pr: Mapping[str, Sequence[records.ObservedCheckRun]],
) -> Fix:
    checks: list[FixedCheck] = []
    for url in prs:
        runs = by_pr.get(url, ())
        before = [r for r in runs if r.observed_at <= run.started_at]
        if not before:
            continue
        head = before[-1].head_sha
        latest = {r.name: r for r in before if r.head_sha == head}
        next_head = next((r.head_sha for r in runs if r.observed_at > run.started_at and r.head_sha != head), None)
        for name, last in latest.items():
            if _verdict(last.conclusion) != "red":
                continue
            after = next((r for r in runs if r.head_sha == next_head and r.name == name), None)
            checks.append(
                FixedCheck(pr_url=url, name=name, next=None if after is None else _verdict(after.conclusion)),
            )
    return Fix(
        run_id=run.id,
        ticket=run.ticket_key,
        kind=run.kind,
        status=run.status,
        started_at=run.started_at,
        cost_usd=run.cost_usd,
        checks=checks,
    )


# A kick, with the checks red on the head it replaced and how each one's first run on the head it pushed ended.
def _kick(
    kick: records.FlakyKick,
    kicks: Iterable[records.FlakyKick],
    kick_runs: Mapping[int, records.Run],
    runs: Iterable[records.ObservedCheckRun],
) -> Kick:
    latest: dict[str, records.ObservedCheckRun] = {}
    first_after: dict[str, records.ObservedCheckRun] = {}
    for r in runs:
        if r.head_sha == kick.from_head:
            latest[r.name] = r
        elif r.head_sha == kick.to_head:
            first_after.setdefault(r.name, r)
    red_before = sorted(name for name, r in latest.items() if _verdict(r.conclusion) == "red")
    run = kick_runs.get(kick.run_id)
    observed = next((r.pr_url for r in (*latest.values(), *first_after.values())), None)
    return Kick(
        run_id=kick.run_id,
        repo=kick.repo,
        branch=kick.branch,
        pr_url=(None if run is None else _named_pr(run, kick.repo)) or observed,
        kicked_at=kick.kicked_at,
        kick=_place(kick, kicks),
        red_before=red_before,
        still_red=[n for n in red_before if n in first_after and _verdict(first_after[n].conclusion) == "red"],
        checked=any(n in first_after for n in red_before),
    )


# The PR a run's result named for `repo`: its `prs` entry, or its one `pr`.
def _named_pr(run: records.Run, repo: str) -> str | None:
    result = contract.stored_object(run.result_json)
    prs = result.get("prs")
    named = cast("dict[str, object]", prs).get(repo) if isinstance(prs, dict) else result.get("pr")
    return next(iter(contract.stored_prs({"pr": named})), None)


# Which of its head's kicks `kick` was, from 1: the length of the chain of kicks on its branch that ends with it, as
# `runs.flaky_kicks.spent` walks it.
def _place(kick: records.FlakyKick, kicks: Iterable[records.FlakyKick]) -> int:
    made = {k.to_head: k.from_head for k in kicks if (k.repo, k.branch) == (kick.repo, kick.branch)}
    head, count = kick.to_head, 0
    # Bounded by the rows: a commit pushed again after a kick replaced it never loops the walk.
    while head in made and count < len(made):
        head = made[head]
        count += 1
    return count


def _kicked_prs(
    kicks: Iterable[Kick],
    tracked: Mapping[str, tracked_prs.TrackedPr],
    kick_runs: Mapping[int, records.Run],
) -> list[KickedPr]:
    by_pr: dict[str, list[Kick]] = {}
    for kick in kicks:
        if kick.pr_url is not None:
            by_pr.setdefault(kick.pr_url, []).append(kick)
    found: list[KickedPr] = []
    for url, made in by_pr.items():
        pr = tracked.get(url)
        run = kick_runs.get(made[0].run_id)
        found.append(
            KickedPr(
                url=url,
                ticket=pr.ticket if pr is not None else None if run is None else run.ticket_key,
                phase=None if pr is None else pr.phase,
                kicks=len(made),
                most=max(k.kick for k in made),
                still_red=sum(1 for k in made if k.still_red),
            ),
        )
    return sorted(found, key=lambda p: (-p.kicks, p.url))
