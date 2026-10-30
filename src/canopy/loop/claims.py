"""A dispatch's claims, checked in code against what the connectors observed (DESIGN §35, ROADMAP M37).

The overseer used to be taken at its word on what authorizes a run: the label it read on the ticket, that a reply came
from an authorized replier, that review feedback came from a trusted reviewer. Where a connector observes the subject,
each is now a reference to an observation the state block showed, checked here before §8's other guards. A refusal is
a decision, as every guard's is:

- `stale`: a subject the dispatch rests on was not observed within `connect.max_age_minutes`: a public ticket, the PR of
  each unit a `resume` names, and the PRs of the ticket a stacked dispatch's `base` is the branch of.
- `unauthorized`: the label was not observed on the ticket; a `resume` for `reply` covers no new comment by an
  authorized replier that is not a worker's, nor a new operator message or comment on one of the ticket's artifacts
  that is authority (DESIGN §38); a `resume` for `review` covers no
  feedback by a trusted reviewer, nor the canopy review it names with `canopy:review` trusted, or covers someone else's
  feedback with no operator message after it among those it carries (D089). With feedback plans on, the approval of
  the plan is the gate instead (§32), so the review check is not made; nor is it on a joint `resume`, which carries
  no unit's `review` cursor, so its review claim stays a claim.
- `unobserved`: a cursor names no item observed for its subject, or passes one the block left out for its bound.
- `handled`: a `resume` for `ci` alone has no failure at its PR's head that a worker has not had: each is at or behind
  the unit's `ci` cursor, or repeats, at the same head and context, one that is, so a re-run that went red to red
  starts nothing (PRIOR_ART, CI newness).

A `resume` moves each cursor of its reasons it leaves out to the newest item of that kind the block showed, short of the
first one these checks would refuse it to cover (`default_cursors`, DESIGN §37): an item past the block's bound, or an
untrusted reviewer's feedback with no operator message after it among those it carries. A cursor passed is kept, so the
overseer passes one only to stop shorter, and the checks above hold it to the same bounds.

The `ticket-set` tool moves cursors too, so its cursors are checked the same way in a tick (`check_cursors`), refused
`unobserved` alone: it starts nothing, so a stale subject is not refused, but the block shows none of a stale subject's
items, so a cursor on one may move no further than the items it already passed. A unit with no PR is unobserved, since
no source reads checks or reviews but a PR's.

A private ticket, which its start record authorizes (§22), is not checked; nor is a subject no source can read, such as
a unit whose PR is not a PR's URL: its claims stay claims, checked again by the worker (D051). Neither, nor a stale
subject, gets a default cursor, since none can be read from a fresh observation. A cursor is a
journal number (§35): it names an item by the number it took when first observed, or a review run by the one it took
when it ended.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import conversation, db, item_numbers, notice, observe, records, review_runs
from canopy.core.config import CANOPY_REVIEWER
from canopy.core.vocab import CheckStatus, ResumeReason, RunKind
from canopy.core.workspace import CheckRole
from canopy.loop import observations, phases
from canopy.runs import artifact_authority
from canopy.runs.dispatch import Refusal

if TYPE_CHECKING:
    from datetime import datetime

    from canopy.core.config import Trust
    from canopy.core.context import Context


def check(
    ctx: Context,
    tick_id: int,
    now: datetime,
    *,
    key: str,
    kind: str,
    label: str | None,
    repos: Sequence[str],
    reasons: Collection[str],
    cursors: Mapping[str, str],
    review_run: int | None,
    base: str | None,
) -> None:
    """Refuse a dispatch whose claims the observations at `now` do not bear out.

    `cursors` are the ones the dispatch moves, by name; a unit's (`review`, `ci`) is of the one repository in `repos`.
    A label left out, a reason on another kind, and a cursor without its reason are left to §8's guards.

    Raises:
        Refusal: `stale`, `unauthorized`, `unobserved`, or `handled`, as the module says.
    """
    if conversation.start_of(ctx.conn, key) is not None:
        # Private, or stopped, which the dispatch guard refuses: its start record, not an observation, authorizes it.
        return
    record = db.get_ticket(ctx.conn, key)
    if record is None:
        return
    reader = observations.Reader.read(ctx, phases.recorded(ctx.conn, tick_id), now, [record])
    units = {u["repo"]: u for u in reader.units(key)}
    _check_subjects(ctx, reader, key, kind=kind, label=label, repos=repos, units=units, base=base)
    one = repos[0] if len(set(repos)) == 1 else None
    pr = _fresh_pr(units.get(one)) if one is not None else None
    _check_comment(reader, record, cursors.get("comment"))
    if pr is not None:
        _check_ci(reader, pr, cursors.get("ci"))
    unit = next((u for u in reader.units_of.get(key, []) if one is not None and u.repo == one), None)
    review = _Review.read(reader, pr, unit, cursors.get("review"), review_run)
    review.check_named()
    if kind != RunKind.RESUME:
        return
    if set(reasons) == {ResumeReason.CI} and pr is not None and unit is not None:
        _check_handled(ctx, reader, pr, unit)
    if ResumeReason.REPLY in reasons:
        _check_reply(ctx, reader, record, cursors)
    gated = ResumeReason.REVIEW in reasons and ctx.config.policy.feedback_plan != "approve"
    if gated and pr is not None:
        review.check_authority(ctx, record, cursors.get("message"))


def check_cursors(
    ctx: Context,
    tick_id: int,
    now: datetime,
    *,
    key: str,
    repo: str | None,
    cursors: Mapping[str, str],
) -> None:
    """Refuse a `ticket-set` whose cursors name no item observed, or pass one the block left out, at `now`.

    `cursors` are the ones it moves, by name; a unit's (`review`, `ci`) is of `repo`. A `review` cursor may name the end
    of any canopy review run of the PR, as the block's `reviews` shows the latest's number.

    Raises:
        Refusal: `unobserved`, as the module says.
    """
    if conversation.start_of(ctx.conn, key) is not None:
        return
    record = db.get_ticket(ctx.conn, key)
    if record is None:
        return
    reader = observations.Reader.read(ctx, phases.recorded(ctx.conn, tick_id), now, [record])
    _check_comment(reader, record, cursors.get("comment"))
    unit = next((u for u in reader.units_of.get(key, []) if repo is not None and u.repo == repo), None)
    seen = next((u for u in reader.units(key) if u["repo"] == repo), None)
    if unit is None or unit.pr_url is None or seen is None or seen["observed"] == "unobserved":
        return
    pr = _fresh_pr(seen)
    if pr is None:
        name = next((n for n in db.UNIT_CURSORS if n in cursors), None)
        if name is None:
            return
        raise Refusal(
            "unobserved",
            f"{name} cursor {cursors[name]}: {key} in {repo} is stale ({seen.get('why')}), so the state block shows "
            "none of its items; move it once the next read observes them",
        )
    _check_ci(reader, pr, cursors.get("ci"))
    _Review.read(reader, pr, unit, cursors.get("review"), None, any_run=True).check_named()


def default_cursors(
    ctx: Context,
    tick: records.Tick,
    now: datetime,
    *,
    key: str,
    kind: str,
    repos: Sequence[str],
    reasons: Collection[str],
    cursors: Mapping[str, str],
    review_run: int | None,
) -> dict[str, str]:
    """Add each cursor of a `resume`'s reasons it leaves out: the newest item of its kind the block showed (DESIGN §37).

    `reply` moves `comment` and `message`, `ci` moves `ci`, and `review` moves `review`, each short of the first item
    the dispatch may not cover: one past the block's bound, or an untrusted reviewer's feedback with no operator message
    after it among those the dispatch carries. A message counts once the tick had read it (`ticks.message_id`), as the
    block shows them; a `review` cursor may stop at the end of the review run the dispatch names. A cursor defaults only
    from a fresh observation: a ticket's of a fresh candidate, a unit's of the one repository `repos` names, with a
    fresh PR. A private ticket's cursors, and any other kind's, are the overseer's alone.

    Returns:
        `cursors`, with each default added; a cursor passed is kept as it is.
    """
    found = dict(cursors)
    if kind != RunKind.RESUME or conversation.start_of(ctx.conn, key) is not None:
        return found
    record = db.get_ticket(ctx.conn, key)
    if record is None:
        return found
    reader = observations.Reader.read(ctx, phases.recorded(ctx.conn, tick.id), now, [record])
    if ResumeReason.REPLY in reasons:
        found = {**_ticket_defaults(ctx, reader, record, tick.message_id), **found}
    one = repos[0] if len(set(repos)) == 1 else None
    if one is not None:
        # A review cursor's go-ahead is an operator message the dispatch carries, its own default included.
        defaults = _unit_defaults(
            ctx,
            reader,
            record,
            one,
            reasons,
            now=now,
            message=found.get("message"),
            review_run=review_run,
        )
        found = {**defaults, **found}
    return found


def _ticket_defaults(
    ctx: Context,
    reader: observations.Reader,
    record: records.Ticket,
    read: int | None,
) -> dict[str, str]:
    """A `resume` for `reply`'s default `comment` and `message` cursors, of a fresh candidate alone.

    Returns:
        Each that has a new item: the newest comment the block showed, and the newest operator message or authorized
        artifact comment the tick had read, up to message `read`.
    """
    ticket = reader.ticket(record.key)
    if ticket["observed"] != "fresh" or not ticket.get("candidate"):
        return {}
    found: dict[str, str] = {}
    shown = [c["number"] for c in ticket.get("comments", []) if c["number"] is not None]
    if shown:
        found["comment"] = str(max(shown))
    if read is not None:
        said = [*_operator_messages(ctx, record, str(read)), *_artifact_comments(ctx, record, str(read))]
        if said:
            found["message"] = str(max(m.id for m in said))
    return found


def _unit_defaults(
    ctx: Context,
    reader: observations.Reader,
    record: records.Ticket,
    repo: str,
    reasons: Collection[str],
    *,
    now: datetime,
    message: str | None,
    review_run: int | None,
) -> dict[str, str]:
    """A `resume`'s default `ci` and `review` cursors of its unit in `repo`, while its PR is observed fresh.

    No `ci` default while a notice is in force or lately ended: whether it explains a failure, and so holds the check,
    is the overseer's judgment (§8), which a default must not pass.

    Returns:
        Each its reasons move that has an item to move to: the newest failed check at the head, newer than the `ci`
        cursor, and the newest review item it may cover (`_newest_review`).
    """
    pr = _fresh_pr(next((u for u in reader.units(record.key) if u["repo"] == repo), None))
    unit = next((u for u in reader.units_of.get(record.key, []) if u.repo == repo), None)
    if pr is None or unit is None:
        return {}
    found: dict[str, str] = {}
    failed = [c.number for c in _failed_at_head(ctx, reader, pr, repo) if c.number is not None]
    newer = [n for n in failed if item_numbers.newer(n, unit.ci_cursor)]
    if ResumeReason.CI in reasons and newer and not notice.recent(ctx.conn, now):
        found["ci"] = str(max(newer))
    if ResumeReason.REVIEW in reasons:
        newest = _newest_review(ctx, reader, record, pr, unit, message=message, review_run=review_run)
        if newest is not None:
            found["review"] = str(newest)
    return found


def _check_subjects(
    ctx: Context,
    reader: observations.Reader,
    key: str,
    *,
    kind: str,
    label: str | None,
    repos: Sequence[str],
    units: Mapping[str, observations.UnitObservation],
    base: str | None,
) -> None:
    """Refuse a dispatch that rests on a stale subject, or names a label not observed on its ticket.

    Raises:
        Refusal: `stale` or `unauthorized`.
    """
    ticket = reader.ticket(key)
    if ticket["observed"] != "fresh":
        raise Refusal("stale", _stale(key, ticket.get("why")))
    if label is not None:
        _check_label(reader.observed[key], key, label)
    if kind == RunKind.RESUME:
        _check_units(reader, key, repos, units)
    if base is not None:
        _check_blocker(ctx, reader, key, base)


def _stale(what: str, why: str | None) -> str:
    """Return a `stale` refusal's reason: what is old, and that nothing dispatches on it until it is read again."""
    return (
        f"{what} is stale ({why or 'never observed'}): no dispatch rests on an observation older than "
        "connect.max_age_minutes; the next read decides it"
    )


def _check_label(seen: records.ObservedTicket, key: str, label: str) -> None:
    """Refuse a label the tracker source did not observe on the ticket, matched case-insensitively (D051).

    The refusal names no label, as the guard against config names none: the overseer reads them in the block.

    Raises:
        Refusal: `unauthorized`.
    """
    observed = {str(x["name"]).casefold() for x in phases.labels_of(seen)}
    if label.casefold() not in observed:
        raise Refusal(
            "unauthorized",
            f"{label!r} was not on {key} when the tracker source last read it; name a queue label observed on it",
        )


def _check_units(
    reader: observations.Reader,
    key: str,
    repos: Sequence[str],
    units: Mapping[str, observations.UnitObservation],
) -> None:
    """Refuse a `resume` while the PR of a unit it names is stale; a unit with no PR yet has none to be.

    Raises:
        Refusal: `stale`, naming the unit.
    """
    with_pr = {u.repo for u in reader.units_of.get(key, []) if u.pr_url}
    for repo in repos:
        unit = units.get(repo)
        if unit is not None and repo in with_pr and unit["observed"] == "stale":
            raise Refusal("stale", _stale(f"{key} in {repo}", unit.get("why")))


def _check_blocker(ctx: Context, reader: observations.Reader, key: str, base: str) -> None:
    """Refuse a stacked dispatch while a PR of the ticket whose branch is `base` is stale (DESIGN §10).

    A base no ticket's branch names is left to the dispatch guard; a PR no source covers is not refused.

    Raises:
        Refusal: `stale`, naming the blocker's unit.
    """
    query = records.select(records.Ticket).where("branch = ? AND key != ?", base, key)
    for blocker in query.all(ctx.conn):
        with_pr = {u.repo for u in reader.units_of.get(blocker.key, []) if u.pr_url}
        for unit in reader.units(blocker.key):
            if unit["repo"] in with_pr and unit["observed"] == "stale":
                raise Refusal("stale", _stale(f"blocker {blocker.key} in {unit['repo']}", unit.get("why")))


def _fresh_pr(unit: observations.UnitObservation | None) -> observations.PrObservation | None:
    """Return a unit's PR when it is observed fresh, else None: a stale one is refused, an unobserved one unchecked."""
    if unit is None or unit["observed"] != "fresh":
        return None
    return unit.get("pr")


def _check_comment(reader: observations.Reader, record: records.Ticket, cursor: str | None) -> None:
    """Refuse a `comment` cursor that is the number of no observed comment, or of one past what the block showed.

    The block shows a ticket's comments past its `comment` cursor, up to its bound; a non-candidate's, none. A cursor
    at or before the `comment` cursor passes nothing new.

    Raises:
        Refusal: `unobserved`.
    """
    if cursor is None:
        return
    comments = reader.comments.get(record.key, [])
    named = _number(cursor)
    if named is None or all(c.number != named for c in comments):
        raise Refusal(
            "unobserved",
            f"comment cursor {cursor} is the number of no comment observed on {record.key}; take it from a comment's "
            "number in the state block",
        )
    shown = {c["number"] for c in reader.ticket(record.key).get("comments", [])}
    new = {c.number for c in observations.past_comments(comments, record.comment_cursor)}
    if named in new and named not in shown:
        raise Refusal(
            "unobserved",
            f"comment cursor {cursor} passes comments on {record.key} the state block left out; advance it no "
            "further than the newest comment it shows",
        )


def _check_ci(reader: observations.Reader, pr: observations.PrObservation, cursor: str | None) -> None:
    """Refuse a `ci` cursor that is the number of no check run observed at the PR's head, as the block shows its checks.

    Raises:
        Refusal: `unobserved`.
    """
    if cursor is None:
        return
    runs = {c.number for c in reader.checks.get(pr["url"], []) if c.head_sha == pr["head"] and c.number is not None}
    if _number(cursor) not in runs:
        raise Refusal(
            "unobserved",
            f"ci cursor {cursor} is the number of no check run observed at the head of {pr['url']}; take it from a "
            "failed check's number in the state block",
        )


def _check_handled(
    ctx: Context,
    reader: observations.Reader,
    pr: observations.PrObservation,
    unit: records.TicketUnit,
) -> None:
    """Refuse a `resume` for CI alone when every failure at the PR's head is one a worker already had (DESIGN §35).

    A failure was had when its run is at or behind the unit's `ci` cursor, a journal number, or when a failure of the
    same context at the same head is, as `observed_check_runs` keeps them: a re-run that went red again. Every failure
    is new while the cursor is empty, as the derivation reads them. One with no run, a commit status, is new here too,
    though the derivation shows it only while the cursor is empty: with no run to compare, the guard lets it through
    rather than refuse what it cannot tell had. A check its repository gives a role other than CI is not CI, and a
    head with no failure is not refused here.

    Raises:
        Refusal: `handled`.
    """
    cursor = unit.ci_cursor
    if cursor is None:
        return
    failed = _failed_at_head(ctx, reader, pr, unit.repo)
    query = records.select(records.ObservedCheckRun).where(
        "pr_url = ? AND head_sha = ? AND number <= ?",
        pr["url"],
        pr["head"],
        cursor,
    )
    runs = query.all(ctx.conn)
    behind = {r.name for r in runs if r.conclusion in observe.FAILED}
    if not failed or any(c.number is None or (c.number > cursor and c.name not in behind) for c in failed):
        return
    names = ", ".join(sorted({c.name for c in failed}))
    raise Refusal(
        "handled",
        f"every failed check at the head of {pr['url']} ({names}) failed at that head at or behind the ci cursor "
        f"{cursor}, so a worker already had it: a re-run that went red again starts no resume for ci alone",
    )


def _failed_at_head(
    ctx: Context,
    reader: observations.Reader,
    pr: observations.PrObservation,
    repo: str | None,
) -> list[records.ObservedCheck]:
    """The CI checks that failed at a PR's head: those its repository gives no other role (DESIGN §30).

    A check that waits on a person, gates the merge, or is ignored is not CI.

    Returns:
        The checks, in the order the block reads them.
    """
    roles = ctx.workspace.check_roles(repo)
    return [
        c
        for c in reader.checks.get(pr["url"], [])
        if c.head_sha == pr["head"]
        and roles.get(c.name, CheckRole.CI) is CheckRole.CI
        and c.status is CheckStatus.COMPLETED
        and c.conclusion in observe.FAILED
    ]


def _check_reply(ctx: Context, reader: observations.Reader, record: records.Ticket, cursors: Mapping[str, str]) -> None:
    """Refuse a `resume` for `reply` that covers neither a new authorized reply nor a new operator message (§7).

    An authorized reply is a comment by an account in `trust.authorized_repliers` that is not a worker's (D069). It is
    covered past the ticket's `comment` cursor and up to the one carried, by their numbers. An operator message is past
    its `message` cursor, up to the one carried, and so is a comment on one of its artifacts that is authority
    (`artifact_authority`, §38).

    Raises:
        Refusal: `unauthorized`.
    """
    comment = _number(cursors.get("comment") or "")
    if comment is not None:
        repliers = set(ctx.config.trust.authorized_repliers)
        new = observations.past_comments(reader.comments.get(record.key, []), record.comment_cursor)
        covered = [c for c in new if c.number is not None and c.number <= comment]
        if any(c.author in repliers and c.source != "worker" for c in covered):
            return
    message = cursors.get("message")
    if _operator_messages(ctx, record, message) or _artifact_comments(ctx, record, message):
        return
    raise Refusal(
        "unauthorized",
        f"a resume for reply needs a cursor past what authorizes it: comment= at or past a new comment on {record.key} "
        "by an authorized replier that is not a worker's, or message= at or past a new operator message or artifact "
        "comment",
    )


def _operator_messages(ctx: Context, record: records.Ticket, cursor: str | None) -> list[records.Message]:
    """The operator's messages on the ticket past its `message` cursor, up to `cursor`; none without one.

    Returns:
        The messages, oldest first.
    """
    if cursor is None or not cursor.isdigit():
        return []
    after = max(record.last_message_id or 0, record.forgotten_message_id or 0)
    found = conversation.operator_messages_after(ctx.conn, record.key, after)
    return [m for m in found if m.id <= int(cursor)]


def _artifact_comments(ctx: Context, record: records.Ticket, cursor: str | None) -> list[records.Message]:
    """The messages of the ticket's comments on artifacts that are authority, past its `message` cursor, up to `cursor`.

    Returns:
        The messages, oldest first; none without a cursor.
    """
    if cursor is None or not cursor.isdigit():
        return []
    authors = frozenset(ctx.config.artifacts.authorized_authors)
    found = artifact_authority.authorized(ctx.conn, record.key, authors, after=record.last_message_id or 0)
    return [m for m in found if m.id <= int(cursor)]


def _newest_review(
    ctx: Context,
    reader: observations.Reader,
    record: records.Ticket,
    pr: observations.PrObservation,
    unit: records.TicketUnit,
    *,
    message: str | None,
    review_run: int | None,
) -> int | None:
    """The newest review item the block showed on a unit's PR that a `resume` for `review` may cover, by its number.

    It stops short of the first new item past the block's bound, and of the first untrusted reviewer's feedback with no
    operator message after it among those up to `message` (D089). The end of `review_run`, a canopy review run of the
    PR, counts as an item when it comes before that.

    Returns:
        The number; None when none is new, or the first new item is one it may not cover.
    """
    trust = ctx.config.trust
    trusted = {t.lower() for t in trust.trusted_reviewers}
    said = [db.parse_time(m.at) for m in _operator_messages(ctx, record, message)]
    new = observations.new_reviews(reader.reviews.get(pr["url"], []), unit.review_cursor)
    covered: list[int] = []
    stop: int | None = None
    for n, r in enumerate(new):
        if r.number is None:
            # No cursor passes it: an item with no number stays newer than any.
            continue
        if n >= observations.MAX_NEW_ITEMS or (_feedback(r, pr, trust) and not _go_ahead(r, trusted, said)):
            stop = r.number
            break
        covered.append(r.number)
    run = None if review_run is None else review_runs.get_review_run(ctx.conn, review_run)
    end = run.number if run is not None and run.pr_url == pr["url"] else None
    if end is not None and item_numbers.newer(end, unit.review_cursor) and (stop is None or end < stop):
        covered.append(end)
    return max(covered, default=None)


def _feedback(r: records.ObservedReview, pr: observations.PrObservation, trust: Trust) -> bool:
    """Whether a review item is feedback, and neither the PR author's, under whom workers post, nor a worker's (D069).

    Returns:
        True for a review comment, a change request, or a review that says something, by anyone else.
    """
    author = (pr["author"] or "").lower()
    marked = conversation.worker_marked(r.body, trust.comment_prefix, trust.comment_suffix)
    return phases.is_feedback(r) and (r.author or "").lower() != author and not marked


def _go_ahead(r: records.ObservedReview, trusted: AbstractSet[str], said: Collection[datetime]) -> bool:
    """Whether a worker may address a review item: a trusted reviewer's, or one an operator message in `said` follows.

    Returns:
        True if it may.
    """
    return (r.author or "").lower() in trusted or _after_any(said, r.created_at)


@dataclass(frozen=True)
class _Review:
    """What a dispatch's `review` cursor and review run cover of one unit's fresh PR (DESIGN §7, D089)."""

    #: The unit, `KEY in repo`; None without a fresh PR to check against.
    subject: str | None
    pr: observations.PrObservation | None
    #: The `review` cursor the dispatch carries.
    cursor: str | None
    #: Every review item observed on the PR, in the order the block reads them.
    items: Sequence[records.ObservedReview]
    #: The items past the unit's `review` cursor and up to the one carried.
    covered: Sequence[records.ObservedReview]
    #: The new items the block showed, by kind and id.
    shown: AbstractSet[tuple[str, int]]
    #: The canopy review run the dispatch names, if the journal has it.
    run: records.ReviewRun | None
    #: The number each canopy review run the cursor may name took when it ended: the one named, or with `any_run` every
    #: run of the PR.
    ends: AbstractSet[int]

    @classmethod
    def read(
        cls,
        reader: observations.Reader,
        pr: observations.PrObservation | None,
        unit: records.TicketUnit | None,
        cursor: str | None,
        review_run: int | None,
        *,
        any_run: bool = False,
    ) -> _Review:
        """Read what a `review` cursor covers on a unit's fresh PR, past the unit's own cursor and up to it.

        With `any_run`, the cursor may name the end of any canopy review run of the PR, not only the one named.

        Returns:
            The cover: no items without a fresh PR or a cursor, with the review run the dispatch names either way. A
            run the journal does not have is left to `review_run`'s own check, which refuses it.
        """
        conn = reader.ctx.conn
        run = None if review_run is None else review_runs.get_review_run(conn, review_run)
        if pr is None or unit is None:
            return cls(
                subject=None,
                pr=None,
                cursor=None,
                items=(),
                covered=(),
                shown=frozenset(),
                run=run,
                ends=frozenset(),
            )
        runs: Sequence[records.ReviewRun] = (
            review_runs.review_runs_of(conn, pr["url"]) if any_run else [run] if run else []
        )
        ends = frozenset(r.number for r in runs if r.number is not None)
        items = reader.reviews.get(pr["url"], [])
        new = observations.new_reviews(items, unit.review_cursor)
        upto = _number(cursor or "")
        covered = [r for r in new if upto is not None and not item_numbers.newer(r.number, upto)]
        shown = frozenset((r.item.value, r.id) for r in new[: observations.MAX_NEW_ITEMS])
        subject = f"{unit.ticket_key} in {unit.repo}"
        return cls(
            subject=subject,
            pr=pr,
            cursor=cursor,
            items=items,
            covered=covered,
            shown=shown,
            run=run,
            ends=ends,
        )

    def check_named(self) -> None:
        """Refuse a `review` cursor that is no observed item's number, or passes an item the block left out.

        The number a review run it may name took when it ended is an item's number too, as the block's `reviews` shows.

        Raises:
            Refusal: `unobserved`.
        """
        if self.pr is None or self.cursor is None:
            return
        numbers = {r.number for r in self.items if r.number is not None} | self.ends
        if _number(self.cursor) not in numbers:
            raise Refusal(
                "unobserved",
                f"review cursor {self.cursor} is the number of no review item observed on {self.pr['url']}, nor of a "
                "review run it may name; take it from an item the state block shows",
            )
        left_out = [r for r in self.covered if (r.item.value, r.id) not in self.shown]
        if left_out:
            raise Refusal(
                "unobserved",
                f"review cursor {self.cursor} passes {len(left_out)} review items on {self.pr['url']} the state block "
                "left out; advance it no further than the newest item it shows",
            )

    def check_authority(self, ctx: Context, record: records.Ticket, message: str | None) -> None:
        """Refuse a `resume` for `review` that covers no feedback it may address, or someone else's without a go-ahead.

        Feedback is a review comment, a change request, or a review that says something, not the PR author's, under
        whom workers post, nor a worker's (D069). A trusted reviewer's authorizes the run, as does the canopy review it
        names with `canopy:review` trusted; anyone else's needs an operator message after it, carried by `message`.

        Raises:
            Refusal: `unauthorized`.
        """
        trust = ctx.config.trust
        trusted = {t.lower() for t in trust.trusted_reviewers}
        pr = self.pr
        feedback = [] if pr is None else [r for r in self.covered if _feedback(r, pr, trust)]
        said = [db.parse_time(m.at) for m in _operator_messages(ctx, record, message)]
        for r in feedback:
            if not _go_ahead(r, trusted, said):
                raise Refusal(
                    "unauthorized",
                    f"review {r.item.value} {r.id} on {self.subject} is not a trusted reviewer's: a resume addresses "
                    "it only with an operator message after it, carried by message=",
                )
        if feedback:
            return
        if self.run is not None and (CANOPY_REVIEWER in trusted or _after_any(said, self.run.ended_at)):
            return
        raise Refusal(
            "unauthorized",
            f"a resume for review covers no feedback by a trusted reviewer on {self.subject or record.key}, nor a "
            "canopy review it may address: carry review= at the newest item it handles, or name the review run",
        )


def _number(cursor: str) -> int | None:
    """Read a cursor the overseer passed as a journal number.

    Returns:
        The number; None when it is not one, which names nothing.
    """
    return int(cursor) if cursor.isascii() and cursor.isdigit() else None


def _after_any(said: Collection[datetime], stamp: str | None) -> bool:
    """Whether an operator message in `said` came after `stamp`: after anything, for an item with no time.

    Returns:
        True if one did.
    """
    if stamp is None:
        return bool(said)
    at = db.parse_time(stamp)
    return any(m > at for m in said)
