"""A dispatch's claims, checked in code against what the connectors observed (DESIGN §35, ROADMAP M37).

The overseer used to be taken at its word on what authorizes a run: the label it read on the ticket, that a reply came
from an authorized replier, that review feedback came from a trusted reviewer. Where a connector observes the subject,
each is now a reference to an observation the state block showed, checked here before §8's other guards. A refusal is
a decision, as every guard's is:

- `stale`: a subject the dispatch rests on was not observed within `connect.max_age_minutes`: a public ticket, the PR of
  each unit a `resume` names, and the PRs of the ticket a stacked dispatch's `base` is the branch of.
- `unauthorized`: the label was not observed on the ticket; a `resume` for `reply` carries no cursor to a new comment
  by an authorized replier that is not a worker's, nor to a new operator message; a `resume` for `review` covers no
  feedback by a trusted reviewer, nor the canopy review it names with `canopy:review` trusted, or covers someone else's
  feedback with no operator message after it among those it carries (D089). With feedback plans on, the approval of
  the plan is the gate instead (§32), so the review check is not made; nor is it on a joint `resume`, which carries
  no unit's `review` cursor, so its review claim stays a claim.
- `unobserved`: a cursor names no item observed for its subject, or passes one the block left out for its bound.

`canopy ticket set` moves cursors too, so its cursors are checked the same way in a tick (`check_cursors`), refused
`unobserved` alone: it starts nothing, so a stale subject is not refused, but the block shows none of a stale subject's
items, so a cursor on one may move no further than the items it already passed. A unit with no PR is unobserved, since
no source reads checks or reviews but a PR's.

A private ticket, which its start record authorizes (§22), is not checked; nor is a subject no source covers, such as
every ticket without a `tracker` source: its claims stay claims, checked again by the worker (D051). Cursors are still
the source's ids and times (§7), so a `review` cursor names an item by its time, to the second.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import conversation, db, records, review_runs, sql
from canopy.core.config import CANOPY_REVIEWER
from canopy.core.vocab import ResumeReason, RunKind
from canopy.loop import observations, phases
from canopy.runs.dispatch import Refusal

if TYPE_CHECKING:
    from datetime import datetime

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
        Refusal: `stale`, `unauthorized`, or `unobserved`, as the module says.
    """
    if conversation.start_of(ctx.conn, key) is not None:
        # Private, or stopped, which the dispatch guard refuses: its start record, not an observation, authorizes it.
        return
    record = db.get_ticket(ctx.conn, key)
    if record is None:
        return
    reader = observations.Reader.read(ctx, tick_id, now, [record])
    units = {u["repo"]: u for u in reader.units(key)}
    tracked = _check_subjects(ctx, reader, key, kind=kind, label=label, repos=repos, units=units, base=base)
    one = repos[0] if len(set(repos)) == 1 else None
    pr = _fresh_pr(units.get(one)) if one is not None else None
    if tracked:
        _check_comment(reader, record, cursors.get("comment"))
    if pr is not None:
        _check_ci(reader, pr, cursors.get("ci"))
    unit = next((u for u in reader.units_of.get(key, []) if one is not None and u.repo == one), None)
    review = _Review.read(reader, pr, unit, cursors.get("review"), review_run)
    review.check_named()
    if kind != RunKind.RESUME:
        return
    if tracked and ResumeReason.REPLY in reasons:
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
    """Refuse a `ticket set` whose cursors name no item observed, or pass one the block left out, at `now`.

    `cursors` are the ones it moves, by name; a unit's (`review`, `ci`) is of `repo`. A `review` cursor may name the end
    of any canopy review run of the PR, as the block's `reviewed_at` shows the latest.

    Raises:
        Refusal: `unobserved`, as the module says.
    """
    if conversation.start_of(ctx.conn, key) is not None:
        return
    record = db.get_ticket(ctx.conn, key)
    if record is None:
        return
    reader = observations.Reader.read(ctx, tick_id, now, [record])
    if reader.ticket(key)["observed"] != "unobserved":
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
) -> bool:
    """Refuse a dispatch that rests on a stale subject, or names a label not observed on its ticket.

    Returns:
        Whether the ticket is observed fresh; False when no source covers it, so its label and replies stay claims.

    Raises:
        Refusal: `stale` or `unauthorized`.
    """
    ticket = reader.ticket(key)
    if ticket["observed"] == "stale":
        raise Refusal("stale", _stale(key, ticket.get("why")))
    tracked = ticket["observed"] == "fresh"
    if tracked and label is not None:
        _check_label(reader.observed[key], key, label)
    if kind == RunKind.RESUME:
        _check_units(reader, key, repos, units)
    if base is not None:
        _check_blocker(ctx, reader, key, base)
    return tracked


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
    query = sql.select("*").from_("tickets").where("branch = ? AND key != ?", base, key)
    for blocker in records.fetch_all(ctx.conn, records.Ticket, query):
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
    """Refuse a `comment` cursor that names no observed comment, or one past what the block showed.

    The block shows a ticket's comments past its `comment` cursor, up to its bound; a non-candidate's, none. A cursor
    at or before the `comment` cursor passes nothing new.

    Raises:
        Refusal: `unobserved`.
    """
    if cursor is None:
        return
    comments = reader.comments.get(record.key, [])
    if all(c.id != cursor for c in comments):
        raise Refusal("unobserved", f"comment cursor {cursor} names no comment observed on {record.key}")
    shown = {c["id"] for c in reader.ticket(record.key).get("comments", [])}
    new = {c.id for c in observations.past_comments(comments, record.last_comment_id)}
    if cursor in new and cursor not in shown:
        raise Refusal(
            "unobserved",
            f"comment cursor {cursor} passes comments on {record.key} the state block left out; advance it no "
            "further than the newest comment it shows",
        )


def _check_ci(reader: observations.Reader, pr: observations.PrObservation, cursor: str | None) -> None:
    """Refuse a `ci` cursor that names no check run observed at the PR's head, as the block shows its checks.

    Raises:
        Refusal: `unobserved`.
    """
    if cursor is None:
        return
    runs = {str(c.run_id) for c in reader.checks.get(pr["url"], []) if c.head_sha == pr["head"] and c.run_id}
    if cursor not in runs:
        raise Refusal("unobserved", f"ci cursor {cursor} names no check run observed at the head of {pr['url']}")


def _check_reply(ctx: Context, reader: observations.Reader, record: records.Ticket, cursors: Mapping[str, str]) -> None:
    """Refuse a `resume` for `reply` that carries neither a new authorized reply nor a new operator message (§7).

    An authorized reply is a comment by an account in `trust.authorized_repliers`, by its id, that is not a worker's
    (D069), past the ticket's `comment` cursor. An operator message is past its `message` cursor, up to the one carried.

    Raises:
        Refusal: `unauthorized`.
    """
    comment = cursors.get("comment")
    if comment is not None:
        repliers = set(ctx.config.trust.authorized_repliers)
        new = observations.past_comments(reader.comments.get(record.key, []), record.last_comment_id)
        if any(c.id == comment and c.author in repliers and c.source != "worker" for c in new):
            return
    if _operator_messages(ctx, record, cursors.get("message")):
        return
    raise Refusal(
        "unauthorized",
        f"a resume for reply needs a cursor to what authorizes it: comment= at a new comment on {record.key} by an "
        "authorized replier that is not a worker's, or message= at a new operator message",
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
    #: When each canopy review run the cursor may name ended: the one named, or with `any_run` every run of the PR.
    ends: Sequence[str]

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
            return cls(subject=None, pr=None, cursor=None, items=(), covered=(), shown=frozenset(), run=run, ends=())
        runs: Sequence[records.ReviewRun] = (
            review_runs.review_runs_of(conn, pr["url"]) if any_run else [run] if run else []
        )
        ends = [r.ended_at for r in runs if r.ended_at is not None]
        items = reader.reviews.get(pr["url"], [])
        since = phases.review_cursor(unit.last_review_id)
        new = [r for r in items if phases.newer(r.created_at, since)]
        upto = phases.review_cursor(cursor)
        covered = [r for r in new if upto is not None and not phases.newer(r.created_at, upto)]
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
        """Refuse a `review` cursor that is no observed item's time, or passes an item the block left out.

        A review run's end it may name is an item's time too, as the block's `reviewed_at`.

        Raises:
            Refusal: `unobserved`.
        """
        if self.pr is None or self.cursor is None:
            return
        at = phases.review_cursor(self.cursor)
        stamps = [r.created_at for r in self.items] + list(self.ends)
        if at is None or not any(s is not None and _second(s) == at.replace(microsecond=0) for s in stamps):
            raise Refusal(
                "unobserved",
                f"review cursor {self.cursor} is the time of no review item observed on {self.pr['url']}, nor of a "
                "review run's end it may name; take it from an item the state block shows",
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
        author = ((self.pr["author"] if self.pr is not None else None) or "").lower()
        feedback = [
            r
            for r in self.covered
            if phases.is_feedback(r)
            and (r.author or "").lower() != author
            and not conversation.worker_marked(r.body, trust.comment_prefix, trust.comment_suffix)
        ]
        said = [db.parse_time(m.at) for m in _operator_messages(ctx, record, message)]
        for r in feedback:
            if (r.author or "").lower() not in trusted and not _after_any(said, r.created_at):
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


def _second(stamp: str) -> datetime:
    return db.parse_time(stamp).replace(microsecond=0)


def _after_any(said: Collection[datetime], stamp: str | None) -> bool:
    """Whether an operator message in `said` came after `stamp`: after anything, for an item with no time.

    Returns:
        True if one did.
    """
    if stamp is None:
        return bool(said)
    at = db.parse_time(stamp)
    return any(m > at for m in said)
