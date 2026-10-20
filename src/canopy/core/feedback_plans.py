"""Plans before feedback runs (DESIGN §32, ROADMAP M54): a feedback plan's row, its items, and the gate it opens.

A feedback plan is §25's plan written for what came back to a ticket's PRs, before the `resume` that acts on it. Its
file is a plan's file (`plans.path_for`): the same operator-only directory, named for the run that wrote it, written
once and read bounded, never through a link. The journal's `feedback_plans` row holds what canopy decides by, its
status, the file's hash as written, and the hash the operator approved; `feedback_plan_items` holds the items its
result line named, each a review or review comment by the id the `vcs` source observed (DESIGN §29). The repositories a
plan covers are its run's slots. A ticket has at most one feedback plan that is not superseded.

Under `policy.feedback_plan = "approve"`, every `resume` but one whose only reason is `no_pr` waits on an approved
feedback plan that no `resume` has spent (`resume_refusal`), and the `resume` that starts on it spends it (`spend`), in
the transaction that inserts that run: one approval goes ahead once. Approving is the operator's verb alone, every
channel's, refused inside canopy's own runs, and holds the dispatch lock, as approving a ticket's plan does.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict

from canopy.core import conversation, db, drafts, plans, records, replies
from canopy.core.conversation import Refused
from canopy.core.vocab import PlanStatus, Proposal, ResumeReason, ReviewItem, ReviewState, RunKind
from canopy.infra import lock

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from canopy.core.config import Config, Policy, Trust

#: The file in a feedback planner's desk that holds its PRs' items, as the `vcs` source observed them: data to it.
ITEMS = ".canopy-feedback.json"
#: The most items one plan's result line names; past it, the rest are refused, each with a harness note.
MAX_ITEMS = 100
#: A drafted reply's bound, in characters, as a draft's (DESIGN §29).
MAX_REPLY = replies.MAX_DRAFT_CHARS
#: The most refused ids a run's harness note names one by one.
_MAX_NAMED = 10


@dataclass(frozen=True)
class Offered:
    """A review or review comment on one of a plan's PRs, as the `vcs` source observed it: one item it may cover."""

    pr_url: str
    item: ReviewItem
    id: int
    author: str | None
    #: Whether `trust.trusted_reviewers` names its author: shown to the operator, and never a gate (DESIGN §32).
    trusted: bool
    bot: bool
    state: ReviewState | None
    created_at: str | None
    url: str | None
    path: str | None
    line: int | None
    outdated: bool | None
    #: Its text, cut as a mirrored comment's is: model or human text, data to the planner, whoever wrote it.
    body: str


@dataclass(frozen=True)
class Named:
    """An item the planner's result line names: its id, what it proposes, and the reply it would draft."""

    id: int
    proposal: Proposal
    reply: str | None


@dataclass(frozen=True)
class Matched:
    """The planner's items checked against those offered: each one kept, with what it covers, and why the rest were not.

    A refusal is the harness's words, for the run's note.
    """

    kept: Sequence[tuple[Offered, Named]]
    refused: Sequence[str]

    def note(self) -> str:
        """Return the harness's note on the run for the ids it refused, or "" when it refused none."""
        if not self.refused:
            return ""
        named = "; ".join(self.refused[:_MAX_NAMED])
        more = f"; and {len(self.refused) - _MAX_NAMED} more" if len(self.refused) > _MAX_NAMED else ""
        return f"the plan named items its reader did not give it, left out of the plan: {named}{more}"


def needed(policy: Policy, reasons: Collection[str]) -> bool:
    """Whether a `resume` for `reasons` waits on an approved feedback plan (DESIGN §32, What a plan covers).

    Returns:
        True under `policy.feedback_plan = "approve"`, unless its only reason is `no_pr`: a branch with no PR has no
        feedback to plan.
    """
    return policy.feedback_plan == "approve" and set(reasons) != {ResumeReason.NO_PR}


def offered(conn: sqlite3.Connection, trust: Trust, key: str, prs: Sequence[str]) -> list[Offered]:
    """Return each item on `prs` a feedback plan of `key` may cover, as the journal's latest whole read holds them.

    That is every review with text or asking for changes, and every comment on a thread not resolved, but those the
    operator sent through canopy (DESIGN §29), comments carrying a worker's marks (D069), pending reviews, and the items
    an earlier plan of the ticket covered that a `resume` went ahead on. Feedback is not split by reviewer: the trust
    of each item's author is shown, not used (DESIGN §32).

    Returns:
        The items, by PR in the order given, then oldest first.
    """
    sent = drafts.sent_by_pr(conn)
    handled = _handled(conn, key)
    found: list[Offered] = []
    for pr in prs:
        rows = records.fetch_all(
            conn,
            records.ObservedReview,
            "SELECT * FROM observed_reviews WHERE pr_url = ? ORDER BY created_at, item, id",
            (pr,),
        )
        by_pr = sent.get(pr, {})
        for row in rows:
            if _skipped(row, trust, by_pr) or (pr, row.item, row.id) in handled:
                continue
            found.append(
                Offered(
                    pr_url=pr,
                    item=row.item,
                    id=row.id,
                    author=row.author,
                    trusted=row.author is not None and row.author in trust.trusted_reviewers,
                    bot=row.bot,
                    state=row.state,
                    created_at=row.created_at,
                    url=row.url,
                    path=row.path,
                    line=row.line,
                    outdated=row.outdated,
                    body=row.body,
                )
            )
    return found


def _skipped(row: records.ObservedReview, trust: Trust, sent: Mapping[str, Sequence[int]]) -> bool:
    """Whether an observed row is no item for a plan.

    Returns:
        True for the operator's own reply, a worker's, a pending review, a comment on a resolved thread, or a review
        that says nothing of its own.
    """
    if row.item is ReviewItem.COMMENT:
        return row.id in sent.get("comments", ()) or bool(row.resolved) or _marked(row.body, trust)
    if row.id in sent.get("reviews", ()) or row.state is ReviewState.PENDING:
        return True
    return (not row.body.strip() and row.state is not ReviewState.CHANGES_REQUESTED) or _marked(row.body, trust)


def _marked(body: str, trust: Trust) -> bool:
    """Whether `body` carries a worker's marks (D069).

    Returns:
        True when it carries every mark the operator set, and there is one.
    """
    prefix, suffix = trust.comment_prefix, trust.comment_suffix
    if not prefix and not suffix:
        return False
    return body.lstrip().startswith(prefix) and body.rstrip().endswith(suffix)


def _handled(conn: sqlite3.Connection, key: str) -> set[tuple[str, ReviewItem, int]]:
    """The items an earlier feedback plan of `key` covered, whose approval a `resume` went ahead on.

    Returns:
        Each by its PR, kind, and observed id.
    """
    rows = records.fetch_all(
        conn,
        records.FeedbackPlanItem,
        "SELECT i.* FROM feedback_plan_items i JOIN feedback_plans p ON p.id = i.plan_id "
        "WHERE p.ticket_key = ? AND p.spent_run_id IS NOT NULL",
        (key,),
    )
    return {(r.pr_url, r.item, r.item_id) for r in rows}


def items_file(items: Sequence[Offered]) -> str:
    """Return the desk's items file: each item as JSON, its text among its fields, all of it data to the planner."""
    return json.dumps(
        [
            {
                "id": o.id,
                "pr": o.pr_url,
                "item": str(o.item),
                "author": o.author,
                "trusted": o.trusted,
                "bot": o.bot,
                "state": None if o.state is None else str(o.state),
                "created_at": o.created_at,
                "url": o.url,
                "path": o.path,
                "line": o.line,
                "outdated": o.outdated,
                "body": o.body,
            }
            for o in items
        ],
        indent=1,
    )


def match(offered: Sequence[Offered], named: Sequence[Named]) -> Matched:
    """Check the planner's items against those it was given: an id it was not given is refused (DESIGN §32).

    So is an id named twice after the first, an id two items share, and every item past `MAX_ITEMS`. A reply is kept
    only for a change or a decline.

    Returns:
        The items kept, in the order named, and why each other one was refused.
    """
    by_id: dict[int, list[Offered]] = {}
    for o in offered:
        by_id.setdefault(o.id, []).append(o)
    kept: list[tuple[Offered, Named]] = []
    refused: list[str] = []
    seen: set[int] = set()
    for n, item in enumerate(named, start=1):
        found = by_id.get(item.id, [])
        if n > MAX_ITEMS:
            refused.append(f"{item.id}, past the {MAX_ITEMS} items a plan covers")
        elif not found:
            refused.append(f"{item.id}, which is no item of its PRs")
        elif len(found) > 1:
            refused.append(f"{item.id}, which names both a review and a comment")
        elif item.id in seen:
            refused.append(f"{item.id}, named again")
        else:
            seen.add(item.id)
            reply = item.reply if item.proposal in (Proposal.CHANGE, Proposal.DECLINE) else None
            kept.append((found[0], Named(item.id, item.proposal, reply)))
    return Matched(kept=kept, refused=refused)


def record(
    conn: sqlite3.Connection, key: str, run_id: int, written: plans.Written, kept: Sequence[tuple[Offered, Named]]
) -> records.FeedbackPlan:
    """Record the feedback plan run `run_id` wrote for `key`, after its file, as `proposed`, with its items.

    It supersedes the ticket's current feedback plan, waiting, approved, or spent.

    Returns:
        The plan's row.
    """
    with db.transaction(conn):
        _supersede(conn, key)
        [plan] = records.fetch_all(
            conn,
            records.FeedbackPlan,
            "INSERT INTO feedback_plans (ticket_key, run_id, created_at, status, sha256, size) "
            "VALUES (?, ?, ?, ?, ?, ?) RETURNING *",
            (key, run_id, db.now(), PlanStatus.PROPOSED, written.sha256, written.size),
        )
        conn.executemany(
            "INSERT INTO feedback_plan_items (plan_id, number, pr_url, item, item_id, proposal, reply) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (plan.id, number, o.pr_url, o.item, o.id, n.proposal, n.reply)
                for number, (o, n) in enumerate(kept, start=1)
            ],
        )
    return plan


def current(conn: sqlite3.Connection, key: str) -> records.FeedbackPlan | None:
    """The ticket's current feedback plan: the one not superseded, waiting, approved, or spent.

    Returns:
        The plan's row, or None when the ticket has none.
    """
    return records.fetch_one(
        conn,
        records.FeedbackPlan,
        "SELECT * FROM feedback_plans WHERE ticket_key = ? AND status != ?",
        (key, PlanStatus.SUPERSEDED),
    )


def get(conn: sqlite3.Connection, plan_id: int) -> records.FeedbackPlan | None:
    """The feedback plan `plan_id`, whatever its status.

    Returns:
        The plan's row, or None when there is none.
    """
    return records.fetch_one(conn, records.FeedbackPlan, "SELECT * FROM feedback_plans WHERE id = ?", (plan_id,))


def history(conn: sqlite3.Connection, key: str) -> list[records.FeedbackPlan]:
    """Every feedback plan of the ticket, superseded ones included.

    Returns:
        The plans' rows, oldest first.
    """
    return records.fetch_all(
        conn, records.FeedbackPlan, "SELECT * FROM feedback_plans WHERE ticket_key = ? ORDER BY id", (key,)
    )


def items(conn: sqlite3.Connection, plan_id: int) -> list[records.FeedbackPlanItem]:
    """The items a feedback plan covers, in the order its result line named them.

    Returns:
        The items' rows, by number.
    """
    return records.fetch_all(
        conn,
        records.FeedbackPlanItem,
        "SELECT * FROM feedback_plan_items WHERE plan_id = ? ORDER BY number",
        (plan_id,),
    )


def repos(conn: sqlite3.Connection, plan: records.FeedbackPlan) -> tuple[str, ...]:
    """The repositories a feedback plan covers: the units its run leased a slot in.

    Returns:
        Their names, in order.
    """
    rows = conn.execute("SELECT repo FROM run_slots WHERE run_id = ? ORDER BY repo", (plan.run_id,)).fetchall()
    return tuple(str(r[0]) for r in rows)


def approved_text(state_dir: Path, plan: records.FeedbackPlan) -> str | None:
    """The text of an approved feedback plan, if its file still has the hash the operator approved.

    Returns:
        The text, or None when the plan is not approved or its file is missing, unreadable, or no longer as approved:
        what a `resume` refuses as `plan_changed`.
    """
    if plan.status is not PlanStatus.APPROVED:
        return None
    reading = plans.read(plans.path_for(state_dir, plan.ticket_key, plan.run_id))
    return reading.text if reading.sha256 == plan.approved_sha256 else None


def resume_refusal(
    conn: sqlite3.Connection,
    state_dir: Path,
    policy: Policy,
    key: str,
    *,
    repos_named: Sequence[str],
    reasons: Collection[str],
) -> tuple[str, str] | None:
    """Return the guard and reason that refuse a `resume` of `key` over `repos_named` for `reasons`, or None.

    A guard in code, whatever the overseer asks for (DESIGN §32, Approving): with feedback plans on, a `resume` that
    needs one (`needed`) goes ahead only on the ticket's approved feedback plan that no `resume` has spent, covering
    every repository it names, whose file still has the hash the operator approved.

    Returns:
        `unplanned` or `plan_changed` with why, or None when it may go ahead.
    """
    if not needed(policy, reasons):
        return None
    plan = current(conn, key)
    then = f"dispatch `feedback-plan` for {key}'s PRs, or wait for the operator"
    if plan is None or plan.spent_run_id is not None:
        had = "" if plan is None else f": feedback plan {plan.id} went ahead with run {plan.spent_run_id} already"
        return "unplanned", f"{key}'s resume waits on a feedback plan the operator approved{had}; {then}"
    if plan.status is not PlanStatus.APPROVED:
        return "unplanned", f"{key}'s resume waits on feedback plan {plan.id}, which the operator has not approved"
    covered = repos(conn, plan)
    outside = [r for r in repos_named if r not in covered]
    if outside:
        why = f"feedback plan {plan.id} of {key} covers {', '.join(covered)}, not {', '.join(outside)}"
        return "unplanned", f"{why}; resume only the repositories it covers"
    if approved_text(state_dir, plan) is None:
        path = plans.path_for(state_dir, key, plan.run_id)
        why = f"feedback plan {plan.id} of {key}, {path}, is no longer the text the operator approved"
        return "plan_changed", f"{why}; they approve it again"
    return None


def follows(
    conn: sqlite3.Connection, policy: Policy, key: str, reasons: Collection[str]
) -> records.FeedbackPlan | None:
    """The approved feedback plan a `resume` for `reasons` follows, once `resume_refusal` let it through.

    Returns:
        The plan, or None for a `resume` that needs none.
    """
    if not needed(policy, reasons):
        return None
    plan = current(conn, key)
    return plan if plan is not None and plan.status is PlanStatus.APPROVED and plan.spent_run_id is None else None


def spend(conn: sqlite3.Connection, plan_id: int, run_id: int) -> bool:
    """Record that `run_id` went ahead on feedback plan `plan_id`'s approval. Call inside the run's insert.

    Returns:
        False when the plan is no longer approved and unspent, and nothing was recorded: the run must not start.
    """
    row = conn.execute(
        "UPDATE feedback_plans SET spent_run_id = ? WHERE id = ? AND status = ? AND spent_run_id IS NULL RETURNING id",
        (run_id, plan_id, PlanStatus.APPROVED),
    ).fetchone()
    return row is not None


def dispatch_refusal(conn: sqlite3.Connection, policy: Policy, key: str) -> tuple[str, str] | None:
    """Return the guard and reason that refuse a feedback plan run for `key` now, or None (DESIGN §32).

    Only with feedback plans on; and not while the ticket's current feedback plan waits on the operator with no change
    asked, nor while one approved waits for its `resume`: a new plan then would spend a plan run for nothing the
    operator asked for, and supersede what they may be reading.

    Returns:
        `feedback_plan_off` or `bad_plan` with why, or None.
    """
    if policy.feedback_plan != "approve":
        return "feedback_plan_off", 'policy.feedback_plan is not "approve": a resume goes ahead without a plan'
    plan = current(conn, key)
    if plan is None or plan.spent_run_id is not None:
        return None
    ticket = db.get_ticket(conn, key)
    if plan.status is PlanStatus.PROPOSED and (ticket is None or changes_asked(conn, ticket) is None):
        return "bad_plan", f"feedback plan {plan.id} of {key} waits on the operator, who has asked for no change"
    if plan.status is PlanStatus.APPROVED:
        return "bad_plan", f"feedback plan {plan.id} of {key} is approved: dispatch the resume that follows it"
    return None


def approve(
    conn: sqlite3.Connection, state_dir: Path, key: str, *, channel: str, dispatch_lock: Path
) -> records.FeedbackPlan:
    """Approve the ticket's current feedback plan, whole, as its file stands now, recording its hash (DESIGN §32).

    Returns:
        The approved plan's row.

    Raises:
        Refused: `inside_run` inside one of canopy's own ticks or runs; `bad_plan` while a feedback plan run for the
            ticket is running, when it has no current feedback plan, when a `resume` already went ahead on it, when it
            is approved and its file has not changed since, or when its file is missing, unreadable, or no plan.
    """
    conversation.check_operator()
    with lock.hold(dispatch_lock, wait=True), db.transaction(conn):
        running = db.running_run_of(conn, key)
        if running is not None and running.kind == RunKind.FEEDBACK_PLAN:
            raise Refused(
                "bad_plan", f"feedback plan run {running.id} for {key} is running; wait for it, then decide on it"
            )
        plan = current(conn, key)
        if plan is None:
            raise Refused("bad_plan", f"{key} has no feedback plan waiting to be approved")
        if plan.spent_run_id is not None:
            raise Refused("bad_plan", f"run {plan.spent_run_id} went ahead on feedback plan {plan.id} of {key} already")
        path = plans.path_for(state_dir, key, plan.run_id)
        reading = plans.read(path)
        if plan.status is PlanStatus.APPROVED and reading.sha256 == plan.approved_sha256:
            raise Refused(
                "bad_plan", f"feedback plan {plan.id} of {key} is approved, and its file has not changed since"
            )
        if reading.problem is not None:
            raise Refused(
                "bad_plan", f"feedback plan {plan.id}'s file {path} is {reading.problem}, so it cannot be approved"
            )
        [approved] = records.fetch_all(
            conn,
            records.FeedbackPlan,
            "UPDATE feedback_plans SET status = ?, approved_sha256 = ?, approved_at = ?, approved_channel = ? "
            "WHERE id = ? RETURNING *",
            (PlanStatus.APPROVED, reading.sha256, db.now(), channel, plan.id),
        )
    return approved


def waiting(conn: sqlite3.Connection, key: str) -> bool:
    """Whether `canopy plan KEY --approve` is the feedback plan's: one waits, or its approval needs renewing.

    Returns:
        True when the ticket's current feedback plan is waiting, or approved with no `resume` gone ahead on it.
    """
    plan = current(conn, key)
    return plan is not None and plan.spent_run_id is None


def changes_asked(conn: sqlite3.Connection, ticket: records.Ticket) -> str | None:
    """Return when the operator asked for changes no feedback planner has read, or None if they have not.

    That is their latest message on the ticket, newer than its current feedback plan and than its latest feedback plan
    run's start: a reply on a waiting plan asks for changes, as on a ticket's plan (DESIGN §32, Approving).

    Returns:
        The message's time as the journal holds it, or None.
    """
    key = ticket.key
    plan = current(conn, key)
    started = conn.execute(
        "SELECT max(started_at) FROM runs WHERE ticket_key = ? AND kind = ? AND id > ?",
        (key, RunKind.FEEDBACK_PLAN, ticket.forgotten_run_id or 0),
    ).fetchone()[0]
    replied = _replied(conn, ticket)
    since = max(plan.created_at if plan is not None else "", str(started) if started is not None else "")
    return replied if replied is not None and since and replied > since else None


def _replied(conn: sqlite3.Connection, ticket: records.Ticket) -> str | None:
    found = conn.execute(
        "SELECT max(at) FROM messages WHERE subject_kind = ? AND subject_id = ? AND source = 'operator' AND id > ?",
        (conversation.TICKET, ticket.key, ticket.forgotten_message_id or 0),
    ).fetchone()[0]
    return None if found is None else str(found)


class NewestFeedbackPlan(TypedDict):
    """A ticket's newest feedback plan as the state block carries it: never its text, nor its items' (DESIGN §32)."""

    id: int
    status: str
    created_at: str
    repos: list[str]
    #: Whether a `resume` went ahead on its approval, which it spent: the next round needs a plan of its own.
    spent: bool


class FeedbackPlanState(TypedDict):
    """A ticket's `feedback_plan` key in the overseer's state block (DESIGN §32, The overseer's part)."""

    #: Whether its `resume`s wait on an approved feedback plan, but one for `no_pr` alone.
    needed: bool
    #: Each unit's feedback plan runs, and its limit for them, by repository.
    attempts: dict[str, int]
    limits: dict[str, int]
    newest: NewestFeedbackPlan | None
    changes_asked: bool
    #: The latest feedback plan run ended `blocked`, with no operator message since.
    blocked: bool


def state_section(
    conn: sqlite3.Connection,
    config: Config,
    ticket: records.Ticket,
    *,
    attempts: Mapping[str, int],
    limits: Mapping[str, int],
) -> FeedbackPlanState | None:
    """Return a ticket's feedback plan for the overseer's state block, or None when feedback plans do not touch it.

    With `policy.feedback_plan` off, a ticket that never had a feedback plan run has no `feedback_plan` key, so the
    block is as it was before feedback plans (DESIGN §32). `attempts` and `limits` are its units', by repository.
    """
    key = ticket.key
    on = config.policy.feedback_plan == "approve"
    run = conn.execute(
        "SELECT * FROM runs WHERE ticket_key = ? AND kind = ? AND id > ? ORDER BY id DESC LIMIT 1",
        (key, RunKind.FEEDBACK_PLAN, ticket.forgotten_run_id or 0),
    ).fetchone()
    if not on and run is None:
        return None
    newest = records.fetch_one(
        conn, records.FeedbackPlan, "SELECT * FROM feedback_plans WHERE ticket_key = ? ORDER BY id DESC LIMIT 1", (key,)
    )
    replied = _replied(conn, ticket)
    blocked = (
        run is not None
        and run["status"] == "blocked"
        and (replied is None or run["ended_at"] is None or replied <= str(run["ended_at"]))
    )
    return {
        "needed": on,
        "attempts": dict(attempts),
        "limits": dict(limits),
        "newest": None
        if newest is None
        else {
            "id": newest.id,
            "status": newest.status,
            "created_at": newest.created_at,
            "repos": list(repos(conn, newest)),
            "spent": newest.spent_run_id is not None,
        },
        "changes_asked": changes_asked(conn, ticket) is not None,
        "blocked": blocked,
    }


def _supersede(conn: sqlite3.Connection, key: str) -> None:
    """Supersede the ticket's current feedback plan, if it has one. Call inside a transaction."""
    conn.execute(
        "UPDATE feedback_plans SET status = ? WHERE ticket_key = ? AND status != ?",
        (PlanStatus.SUPERSEDED, key, PlanStatus.SUPERSEDED),
    )
