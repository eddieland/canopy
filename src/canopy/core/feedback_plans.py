"""Plans before feedback runs (DESIGN §32, ROADMAP M54): a feedback plan's row, its items, and the gate it opens.

A feedback plan is §25's plan written for what came back to a ticket's PRs, before the `resume` that acts on it. Its
file is a plan's file (`plans.path_for`): the same operator-only directory, named for the run that wrote it, written
once and read bounded, never through a link. The journal's `feedback_plans` row holds what canopy decides by, its
status, the file's hash as written, and the hash the operator approved; `feedback_plan_items` holds the items its
result line named, each a review or review comment by the id the `vcs` source observed (DESIGN §29), or a failed
check, a conflict with the base, or a merged blocker by the id canopy gave it (`feedback_items.check_id`). The
repositories a plan covers are its run's slots, and what it saw of its PRs is recorded with it (`feedback_items`). A
ticket has at most one feedback plan that is not superseded.

Under `policy.feedback_plan = "approve"`, every `resume` but one whose only reason is `no_pr` waits on an approved
feedback plan that no `resume` has spent (`resume_refusal`), and the `resume` that starts on it spends it (`spend`), in
the transaction that inserts that run: one approval goes ahead once. Approving is the operator's verb, every
channel's, refused inside canopy's own runs, and holds the dispatch lock, as approving a ticket's plan does; under
`policy.planner_may_approve`, `record` approves a plan its planner says needs no review as the planner's (§25).

A waiting plan whose PRs changed since it saw them is stale (`feedback_items.changes`): it is planned again once the
quiet period on its PRs passed, and approving it is refused `stale` once, naming what changed (DESIGN §32, Planning
again).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final, TypedDict

from canopy.core import conversation, db, feedback_items, plans, prompts, records, replies, sql
from canopy.core.conversation import Refused
from canopy.core.vocab import PlanEffort, PlanItem, PlanStatus, Proposal, ResumeReason, RunKind, RunStatus
from canopy.infra import lock
from canopy.infra.text import printable

if TYPE_CHECKING:
    import sqlite3
    from datetime import datetime
    from pathlib import Path

    from canopy.core.config import Config, Policy, Trust
    from canopy.core.feedback_items import Item
    from canopy.core.workspace import Workspace

#: The most items one plan's result line names; past it, the rest are refused, each with a harness note.
MAX_ITEMS: Final = 100
#: A drafted reply's bound, in characters, as a draft's (DESIGN §29).
MAX_REPLY: Final = replies.MAX_DRAFT_CHARS
#: The most characters of the operator's own words an approval's message carries, after the sentence naming the
#: plan's items, within an operator message's bound.
MAX_WORDS: Final = conversation.MAX_OPERATOR - 1000
#: The most refused ids a run's harness note names one by one.
_MAX_NAMED: Final = 10
#: The most characters of an item's excerpt or of a plan's line on it, as the PR's page shows them.
MAX_LINE: Final = 200
# An item's heading in a plan's file, at any level, and any heading, which ends the item before it; a fenced code
# block holds no item's first line.
_ITEM_HEADING_RE: Final = re.compile(r"#{1,6}[ \t]+Item[ \t]+(\d{1,20})(?![\d])")
_ANY_HEADING_RE: Final = re.compile(r"#{1,6}(?:[ \t]|$)")
_FENCE_RE: Final = re.compile(r"(?:`{3,}|~{3,})")


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

    kept: Sequence[tuple[Item, Named]]
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


def match(offered: Sequence[Item], named: Sequence[Named]) -> Matched:
    """Check the planner's items against those it was given: an id it was not given is refused (DESIGN §32).

    So is an id named twice after the first, an id two items share, and every item past `MAX_ITEMS`. A reply is kept
    only for a review item's change or decline: a failed check, a conflict, or a merged blocker has no author to
    answer.

    Returns:
        The items kept, in the order named, and why each other one was refused.
    """
    by_id: dict[int, list[Item]] = {}
    for o in offered:
        by_id.setdefault(o.id, []).append(o)
    kept: list[tuple[Item, Named]] = []
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
            answers = found[0].item in (PlanItem.REVIEW, PlanItem.COMMENT)
            reply = item.reply if answers and item.proposal in (Proposal.CHANGE, Proposal.DECLINE) else None
            kept.append((found[0], Named(item.id, item.proposal, reply)))
    return Matched(kept=kept, refused=refused)


def record(
    conn: sqlite3.Connection,
    key: str,
    run_id: int,
    written: plans.Written,
    kept: Sequence[tuple[Item, Named]],
    *,
    snapshot: feedback_items.Snapshot,
    event: Callable[[int, str | None], db.Event | None] | None = None,
    no_review: str | None = None,
    effort: PlanEffort | None = None,
) -> records.FeedbackPlan:
    """Record the feedback plan run `run_id` wrote for `key`, after its file, as `proposed`, with its items.

    It supersedes the ticket's current feedback plan, waiting, approved, or spent. `snapshot` is what the run's read saw
    of its PRs, recorded with it, so what changed on them since can be told (DESIGN §32, Planning again). `no_review` is
    its planner's reason for saying the plan needs no review, under `policy.planner_may_approve`: the plan is then
    recorded `approved` as the planner wrote it, the planner's approval (`plans.PLANNER`), unless it replaces one no
    `resume` has spent, which waited on the operator or was approved by them (DESIGN §32). `event` builds its event from
    its id and that reason when it held, recorded in the same transaction (§20). `effort` is its planner's
    estimate of the work, kept to show beside it.

    Returns:
        The plan's row.
    """
    with db.transaction(conn):
        reason = no_review if planner_may_approve(conn, key) else None
        _supersede(conn, key)
        approved = reason is not None
        now = db.now()
        [plan] = records.fetch_all(
            conn,
            records.FeedbackPlan,
            sql.insert(
                "feedback_plans",
                ticket_key=key,
                run_id=run_id,
                created_at=now,
                status=PlanStatus.APPROVED if approved else PlanStatus.PROPOSED,
                sha256=written.sha256,
                size=written.size,
                approved_sha256=written.sha256 if approved else None,
                approved_at=now if approved else None,
                approved_channel=plans.PLANNER if approved else None,
                approved_reason=reason,
                effort=effort,
            ).returning("*"),
        )
        sql.execute_many(
            conn,
            sql.insert_rows(
                "feedback_plan_items",
                ("plan_id", "number", "pr_url", "item", "item_id", "proposal", "reply"),
            ),
            [
                (plan.id, number, o.pr_url, o.item, o.id, n.proposal, n.reply)
                for number, (o, n) in enumerate(kept, start=1)
            ],
        )
        feedback_items.record(conn, plan.id, snapshot)
        built = event(plan.id, reason) if event is not None else None
        if built is not None:
            db.record_event(conn, built)
    return plan


def planner_may_approve(conn: sqlite3.Connection, key: str) -> bool:
    """Whether `key`'s next feedback plan may be approved on its planner's word (DESIGN §32).

    Returns:
        False when it would replace one no `resume` has spent, which waited on the operator or was approved by them.
    """
    replaced = current(conn, key)
    return replaced is None or replaced.spent_run_id is not None


def current(conn: sqlite3.Connection, key: str) -> records.FeedbackPlan | None:
    """The ticket's current feedback plan: the one not superseded, waiting, approved, or spent.

    Returns:
        The plan's row, or None when the ticket has none.
    """
    return records.fetch_one(
        conn,
        records.FeedbackPlan,
        sql.select("*").from_("feedback_plans").where("ticket_key = ? AND status != ?", key, PlanStatus.SUPERSEDED),
    )


def get(conn: sqlite3.Connection, plan_id: int) -> records.FeedbackPlan | None:
    """The feedback plan `plan_id`, whatever its status.

    Returns:
        The plan's row, or None when there is none.
    """
    return records.fetch_one(
        conn,
        records.FeedbackPlan,
        sql.select("*").from_("feedback_plans").where("id = ?", plan_id),
    )


def of_run(conn: sqlite3.Connection, run_id: int) -> records.FeedbackPlan | None:
    """The feedback plan the run `run_id` wrote, whatever its status.

    Returns:
        The plan's row, or None when the run wrote none: a run of another kind, or a plan run that failed.
    """
    return records.fetch_one(
        conn,
        records.FeedbackPlan,
        sql.select("*").from_("feedback_plans").where("run_id = ?", run_id),
    )


def history(conn: sqlite3.Connection, key: str) -> list[records.FeedbackPlan]:
    """Every feedback plan of the ticket, superseded ones included.

    Returns:
        The plans' rows, oldest first.
    """
    return records.fetch_all(
        conn,
        records.FeedbackPlan,
        sql.select("*").from_("feedback_plans").where("ticket_key = ?", key).order_by("id"),
    )


def items(conn: sqlite3.Connection, plan_id: int) -> list[records.FeedbackPlanItem]:
    """The items a feedback plan covers, in the order its result line named them.

    Returns:
        The items' rows, by number.
    """
    return records.fetch_all(
        conn,
        records.FeedbackPlanItem,
        sql.select("*").from_("feedback_plan_items").where("plan_id = ?", plan_id).order_by("number"),
    )


def authors(conn: sqlite3.Connection, plan_id: int) -> dict[feedback_items.Key, str | None]:
    """Who wrote each item a feedback plan was given, as what it saw recorded them (`feedback_items.record`).

    Returns:
        Each author, None where the source named none, by PR, kind, and observed id.
    """
    rows = records.fetch_all(
        conn,
        records.FeedbackPlanSeen,
        sql.select("*").from_("feedback_plan_seen").where("plan_id = ? AND answers IS NULL", plan_id),
    )
    return {(r.pr_url, PlanItem(r.item), r.item_id): r.author for r in rows}


def repos(conn: sqlite3.Connection, plan: records.FeedbackPlan) -> tuple[str, ...]:
    """The repositories a feedback plan covers: the units its run leased a slot in.

    Returns:
        Their names, in order.
    """
    rows = sql.execute(
        conn,
        sql.select("repo").from_("run_slots").where("run_id = ?", plan.run_id).order_by("repo"),
    ).fetchall()
    return tuple(str(r[0]) for r in rows)


def rationales(text: str) -> dict[int, str]:
    """Why a plan proposes what it does for each item: the first line under its `### Item <id>` heading, as text.

    The heading is the one the planner writes, at any level, and the line is the first holding anything before the
    next heading, a fenced code block passed over; the file's words, cut as `first_line` cuts them, model text for
    the operator to weigh, never an instruction.

    Returns:
        Each item's line by its id; an item with no heading, or nothing under it, has none.
    """
    found: dict[int, str] = {}
    item: int | None = None
    fence = ""
    for raw in text.splitlines():
        line = raw.strip()
        marker = _FENCE_RE.match(line)
        if fence:
            if marker is not None and marker.group(0)[0] == fence[0] and len(marker.group(0)) >= len(fence):
                fence = ""
            continue
        if marker is not None:
            fence = marker.group(0)
            continue
        heading = _ITEM_HEADING_RE.match(line)
        if heading is not None:
            item = int(heading.group(1))
            continue
        if _ANY_HEADING_RE.match(line):
            item = None
            continue
        if item is None or item in found:
            continue
        said = first_line(line)
        if said is not None:
            found[item] = said
    return found


def first_line(text: str) -> str | None:
    """The first line of `text` holding anything, cut to `MAX_LINE` characters: an excerpt of what was said.

    Returns:
        That line, control characters made spaces and whitespace collapsed, with "…" at its end when cut; None when
        no line holds anything.
    """
    lines = (" ".join(printable(line).split()) for line in text.splitlines())
    line = next((line for line in lines if line), None)
    if line is None:
        return None
    return line if len(line) <= MAX_LINE else line[: MAX_LINE - 1] + "…"


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
    conn: sqlite3.Connection,
    policy: Policy,
    key: str,
    reasons: Collection[str],
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
    row = sql.execute(
        conn,
        sql.update("feedback_plans")
        .set(spent_run_id=run_id)
        .where("id = ? AND status = ? AND spent_run_id IS NULL", plan_id, PlanStatus.APPROVED)
        .returning("id"),
    ).fetchone()
    return row is not None


def dispatch_refusal(
    conn: sqlite3.Connection,
    config: Config,
    ws: Workspace,
    key: str,
    *,
    now: datetime,
) -> tuple[str, str] | None:
    """Return the guard and reason that refuse a feedback plan run for `key` now, or None (DESIGN §32).

    Only with feedback plans on; and not while one approved waits for its `resume`, nor while the ticket's current
    feedback plan waits on the operator with no change asked and nothing changed on its PRs since: a new plan then
    would spend a plan run for nothing, and supersede what they may be reading. A stale plan is planned again only once
    the quiet period on its PRs has passed, so a burst of comments makes one plan, not one each (TRUST_MODEL T3).

    Returns:
        `feedback_plan_off`, `bad_plan`, or `quiet` with why, or None.
    """
    if config.policy.feedback_plan != "approve":
        return "feedback_plan_off", 'policy.feedback_plan is not "approve": a resume goes ahead without a plan'
    plan = current(conn, key)
    if plan is None or plan.spent_run_id is not None:
        return None
    if plan.status is PlanStatus.APPROVED:
        return "bad_plan", f"feedback plan {plan.id} of {key} is approved: dispatch the resume that follows it"
    return _waiting_refusal(conn, config, ws, plan, now)


def _waiting_refusal(
    conn: sqlite3.Connection,
    config: Config,
    ws: Workspace,
    plan: records.FeedbackPlan,
    now: datetime,
) -> tuple[str, str] | None:
    """Return why a waiting feedback plan is not planned again now, or None when it may be.

    Returns:
        `bad_plan` while the operator asked for no change and nothing changed on its PRs, `quiet` while it is stale but
        inside the quiet period on them, or None.
    """
    key = plan.ticket_key
    ticket = db.get_ticket(conn, key)
    if ticket is not None and changes_asked(conn, ticket) is not None:
        return None
    found = stale(conn, config, ws, plan, now)
    if not found.changes:
        why = "who has asked for no change, and nothing changed on its PRs since it was written"
        return "bad_plan", f"feedback plan {plan.id} of {key} waits on the operator, {why}"
    if not found.quiet_passed(now) and found.quiet_until is not None:
        minutes = config.policy.feedback_quiet_minutes
        why = f"its PRs had a new item or reply less than {minutes} minutes ago"
        after = db.format_time(found.quiet_until)
        return "quiet", f"feedback plan {plan.id} of {key} is stale, but {why}: plan it again after {after}"
    return None


@dataclass(frozen=True)
class Stale:
    """What changed on a feedback plan's PRs since it saw them, and when the quiet period on them ends (DESIGN §32)."""

    #: Each change, with its reason; empty while the plan is not stale.
    changes: Sequence[feedback_items.Change]
    #: `policy.feedback_quiet_minutes` after the newest item or reply on its PRs; None when they have none with a time.
    quiet_until: datetime | None

    def quiet_passed(self, now: datetime) -> bool:
        """Whether the quiet period on the plan's PRs has passed at `now`.

        Returns:
            True once it ended, or when there is none.
        """
        return self.quiet_until is None or now >= self.quiet_until


def stale(
    conn: sqlite3.Connection,
    config: Config,
    ws: Workspace,
    plan: records.FeedbackPlan,
    now: datetime,
) -> Stale:
    """Compare `plan` with what the connectors observe of its PRs now, in code (DESIGN §32, Planning again).

    The quiet period runs from the newest item or reply on its PRs, or from when the harness first saw the head or
    check conclusion they moved to, the newer: a stream of pushes or a flapping check holds a re-plan as a stream of
    comments does (TRUST_MODEL T3). A check `ws` gives a role other than CI neither makes it stale nor holds it.

    Returns:
        What changed, and when the quiet period on its PRs ends.
    """
    changes = feedback_items.changes(conn, config.trust, plan, ws)
    made = feedback_items.newest(conn, config.trust, feedback_items.prs_of(conn, plan.id))
    moved = feedback_items.moved_at(conn, plan.id, changes, now)
    latest = max((t for t in (made, moved) if t is not None), default=None)
    quiet = None if latest is None else latest + timedelta(minutes=config.policy.feedback_quiet_minutes)
    return Stale(changes=changes, quiet_until=quiet)


def note_moves(conn: sqlite3.Connection, config: Config, ws: Workspace) -> None:
    """Record each waiting feedback plan's PR's head and CI checks, each value timed from when it was first seen.

    Call each tick after the connectors read, so the quiet period runs from the newest move (`stale`). Nothing is
    recorded with feedback plans off.
    """
    if config.policy.feedback_plan != "approve":
        return
    waiting = records.fetch_all(
        conn,
        records.FeedbackPlan,
        sql.select("*").from_("feedback_plans").where("status = ? AND spent_run_id IS NULL", PlanStatus.PROPOSED),
    )
    now = db.now()
    with db.transaction(conn):
        for plan in waiting:
            feedback_items.record_values(conn, ws, plan.id, feedback_items.prs_of(conn, plan.id), now)


def approve(
    conn: sqlite3.Connection,
    state_dir: Path,
    key: str,
    *,
    trust: Trust,
    ws: Workspace,
    channel: str,
    dispatch_lock: Path,
    chosen: Collection[int] = (),
    leave: Collection[int] = (),
    words: str | None = None,
) -> records.FeedbackPlan:
    """Approve the ticket's current feedback plan as its file stands now, whole or by item (DESIGN §32, Approving).

    The approval records the file's hash. `chosen`, when given, names by number the items it approves, and `leave`
    those it does not, approving the rest: the items left out its `resume` does not act on, and the next plan is offered
    them again. It writes an operator message on the ticket, in the same transaction, naming the plan and its items to
    address and to leave, by number and observed id, never quoting them, with the operator's own `words` after, when
    they gave some: the plan's text stays data, and the message is the instruction (TRUST_MODEL T1). The message
    answers no question a run asked, which still waits on a reply. Approving an approved plan again, unspent, sets its
    items afresh, with a message of its own, the newest, which the `resume` reads.

    A waiting plan that is stale is refused once for what changed on its PRs since it was written, which the refusal
    names and records; approving it again, with nothing more changed, approves it, and what changed waits for the next
    plan (DESIGN §32, Planning again). `trust` tells a worker's comments and the operator's sent replies from feedback,
    and `ws` the checks that are not CI from those that are.

    Returns:
        The approved plan's row.

    Raises:
        Refused: `inside_run` inside one of canopy's own ticks or runs; `bad_body` for `words` empty or over
            `MAX_WORDS`; `bad_plan` while a feedback plan run for the ticket is running, when it has no current feedback
            plan, when a `resume` already went ahead on it, when it is approved as asked and its file has not changed
            since, or when its file is missing, unreadable, or no plan; `bad_item` for both `chosen` and `leave`, a
            number in either the plan does not cover, or every item left out; or `stale` the first time a waiting
            plan is approved after its PRs changed, naming what changed.
    """
    conversation.check_operator()
    said_too = _words(words)
    with lock.hold(dispatch_lock, wait=True), db.transaction(conn):
        plan, sha256 = _approvable(conn, state_dir, key)
        covered = items(conn, plan.id)
        left = _left_out(plan, covered, chosen, leave)
        if (
            plan.status is PlanStatus.APPROVED
            and sha256 == plan.approved_sha256
            and left == {i.number for i in covered if i.left_out}
            and said_too is None
        ):
            raise Refused(
                "bad_plan",
                f"feedback plan {plan.id} of {key} is approved, and its file has not changed since",
            )
        changed = feedback_items.changes(conn, trust, plan, ws) if plan.status is PlanStatus.PROPOSED else []
        shown = feedback_items.digest(changed)
        if changed and plan.stale_shown != shown:
            # Recorded, and committed with the transaction before the refusal, so approving again approves it.
            sql.execute(conn, sql.update("feedback_plans").set(stale_shown=shown).where("id = ?", plan.id))
        else:
            return _approved(conn, plan, covered, left, sha256=sha256, channel=channel, words=said_too)
    why = f"feedback plan {plan.id} of {key} is stale: {feedback_items.said(changed)}"
    raise Refused("stale", f"{why}. Approve it again to approve it as it is; what changed waits for the next plan")


def approval_message(
    plan_id: int,
    addressed: Sequence[tuple[int, int]],
    left: Sequence[tuple[int, int]],
    words: str | None,
) -> str:
    """Return the operator message an approval writes: the plan and its items to address and to leave.

    Each item is named by its number and observed id (`prompts.item_names`), never quoted, nor is the plan: their text
    is data, and this message is the instruction (DESIGN §32).

    Returns:
        The message, with the operator's own `words` after it when they gave some.
    """
    named = prompts.item_names
    if not addressed and not left:
        body = f"Go ahead on feedback plan {plan_id} as it says: it covers no item."
    elif not left:
        body = f"Address {named(addressed)} of feedback plan {plan_id}, every item it covers, as it proposes."
    else:
        them = "it" if len(left) == 1 else "them"
        body = (
            f"Address {named(addressed)} of feedback plan {plan_id}, as it proposes. Leave its {named(left)} for the "
            f"next plan: change nothing for {them}, and draft no reply to {them}."
        )
    return body if words is None else f"{body}\n\n{words}"


def _words(words: str | None) -> str | None:
    """The operator's own words for an approval's message, stripped, or None when they gave none.

    Returns:
        The words.

    Raises:
        Refused: (`bad_body`) for words that are empty or over `MAX_WORDS`.
    """
    if words is None:
        return None
    text = words.strip()
    if not text:
        raise Refused("bad_body", "the message is empty; leave it out to approve with none")
    if len(text) > MAX_WORDS:
        raise Refused("bad_body", f"the message is {len(text)} characters; the most is {MAX_WORDS}")
    return text


def _approvable(conn: sqlite3.Connection, state_dir: Path, key: str) -> tuple[records.FeedbackPlan, str]:
    """The ticket's current feedback plan, if the operator may approve it, and its file's hash as it stands now.

    Returns:
        The plan's row, and the hash.

    Raises:
        Refused: (`bad_plan`) as `approve` says.
    """
    running = db.running_run_of(conn, key)
    if running is not None and running.kind == RunKind.FEEDBACK_PLAN:
        raise Refused(
            "bad_plan",
            f"feedback plan run {running.id} for {key} is running; wait for it, then decide on it",
        )
    plan = current(conn, key)
    if plan is None:
        raise Refused("bad_plan", f"{key} has no feedback plan waiting to be approved")
    if plan.spent_run_id is not None:
        raise Refused("bad_plan", f"run {plan.spent_run_id} went ahead on feedback plan {plan.id} of {key} already")
    path = plans.path_for(state_dir, key, plan.run_id)
    reading = plans.read(path)
    if reading.problem is not None or reading.sha256 is None:
        raise Refused(
            "bad_plan",
            f"feedback plan {plan.id}'s file {path} is {reading.problem}, so it cannot be approved",
        )
    return plan, reading.sha256


def _left_out(
    plan: records.FeedbackPlan,
    covered: Sequence[records.FeedbackPlanItem],
    chosen: Collection[int],
    leave: Collection[int],
) -> set[int]:
    """The numbers of the plan's items an approval leaves out: all but `chosen`, or `leave`; none when it names none.

    Returns:
        The numbers.

    Raises:
        Refused: (`bad_item`) for both `chosen` and `leave`, a number the plan does not cover, or every item left out.
    """
    if chosen and leave:
        raise Refused("bad_item", "name the items to approve or those to leave out, not both")
    named = set(chosen or leave)
    numbers = {i.number for i in covered}
    unknown = sorted(named - numbers)
    if unknown:
        has = prompts.item_names([(i.number, i.item_id) for i in covered]) if covered else "no item: approve it whole"
        why = f"feedback plan {plan.id} of {plan.ticket_key} has no item {', '.join(str(n) for n in unknown)}"
        raise Refused("bad_item", f"{why}; it covers {has}")
    left = numbers - named if chosen else named
    if covered and left == numbers:
        why = f"leaving out every item of feedback plan {plan.id} of {plan.ticket_key} approves none"
        raise Refused("bad_item", f"{why}: ask for changes with a reply instead")
    return left


def _approved(
    conn: sqlite3.Connection,
    plan: records.FeedbackPlan,
    covered: Sequence[records.FeedbackPlanItem],
    left: AbstractSet[int],
    *,
    sha256: str,
    channel: str,
    words: str | None,
) -> records.FeedbackPlan:
    """Record the operator's approval of `plan`, with the items numbered `left` left out, and its message.

    Call inside a transaction.

    Returns:
        The approved plan's row.
    """
    sql.execute(conn, sql.update("feedback_plan_items").set(left_out=False).where("plan_id = ?", plan.id))
    if left:
        sql.execute(
            conn,
            sql.update("feedback_plan_items").set(left_out=True).where("plan_id = ?", plan.id).where_in("number", left),
        )
    body = approval_message(
        plan.id,
        [(i.number, i.item_id) for i in covered if i.number not in left],
        [(i.number, i.item_id) for i in covered if i.number in left],
        words,
    )
    # Each approval writes a message of its own, even one worded as an earlier one was, so the newest is the approval
    # in force; and it answers no question a run asked, which still waits on a reply.
    replied = conversation.write_reply(
        conn,
        conversation.Ref(conversation.TICKET, plan.ticket_key),
        body,
        channel=channel,
        submission=f"feedback-plan/{plan.id}/after/{plan.approved_message_id or 0}",
        answers=False,
    )
    [approved] = records.fetch_all(
        conn,
        records.FeedbackPlan,
        sql.update("feedback_plans")
        .set(
            status=PlanStatus.APPROVED,
            approved_sha256=sha256,
            approved_at=db.now(),
            approved_channel=channel,
            approved_reason=None,
            approved_message_id=replied.message_id,
        )
        .where("id = ?", plan.id)
        .returning("*"),
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
    run's start: a reply on a waiting plan asks for changes, as on a ticket's plan (DESIGN §32, Approving). A reply
    after an approval, spent or not, asks for none.

    Returns:
        The message's time as the journal holds it, or None.
    """
    key = ticket.key
    plan = current(conn, key)
    if plan is not None and plan.status is PlanStatus.APPROVED:
        return None
    started = sql.execute(
        conn,
        sql.select("max(started_at)")
        .from_("runs")
        .where("ticket_key = ? AND kind = ? AND id > ?", key, RunKind.FEEDBACK_PLAN, ticket.forgotten_run_id or 0),
    ).fetchone()[0]
    replied = _replied(conn, ticket)
    since = max(plan.created_at if plan is not None else "", str(started) if started is not None else "")
    return replied if replied is not None and since and replied > since else None


def _replied(conn: sqlite3.Connection, ticket: records.Ticket) -> str | None:
    # An approval's own message is an instruction: it answers no question and asks for no change.
    found = sql.execute(
        conn,
        sql.select("max(at)")
        .from_("messages")
        .where("subject_kind = ? AND subject_id = ?", conversation.TICKET, ticket.key)
        .where("source = 'operator' AND id > ?", ticket.forgotten_message_id or 0)
        .where("coalesce(submission, '') NOT GLOB ?", f"{conversation.INSTRUCTION}*"),
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
    #: Whether it waits on the operator and its PRs changed since it was written, as the harness computed this tick;
    #: false once it is approved, since feedback after an approval waits for the next plan (DESIGN §32).
    stale: bool
    #: Whether the quiet period on its PRs has passed, so a stale plan may be planned again.
    quiet_passed: bool


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
    ws: Workspace,
    ticket: records.Ticket,
    *,
    attempts: Mapping[str, int],
    limits: Mapping[str, int],
    now: datetime,
) -> FeedbackPlanState | None:
    """Return a ticket's feedback plan for the overseer's state block, or None when feedback plans do not touch it.

    With `policy.feedback_plan` off, a ticket that never had a feedback plan run has no `feedback_plan` key, so the
    block is as it was before feedback plans (DESIGN §32). `attempts` and `limits` are its units', by repository.
    Whether its newest plan is stale, and the quiet period on its PRs passed at `now`, is computed here, after the
    tick's connectors read, so the overseer compares no times.
    """
    key = ticket.key
    on = config.policy.feedback_plan == "approve"
    run = records.fetch_one(
        conn,
        records.Run,
        sql.select("*")
        .from_("runs")
        .where("ticket_key = ? AND kind = ? AND id > ?", key, RunKind.FEEDBACK_PLAN, ticket.forgotten_run_id or 0)
        .order_by("id DESC")
        .limit(1),
    )
    if not on and run is None:
        return None
    newest = records.fetch_one(
        conn,
        records.FeedbackPlan,
        sql.select("*").from_("feedback_plans").where("ticket_key = ?", key).order_by("id DESC").limit(1),
    )
    replied = _replied(conn, ticket)
    blocked = (
        run is not None
        and run.status is RunStatus.BLOCKED
        and (replied is None or run.ended_at is None or replied <= run.ended_at)
    )
    return {
        "needed": on,
        "attempts": dict(attempts),
        "limits": dict(limits),
        "newest": None if newest is None else _newest(conn, config, ws, newest, now),
        "changes_asked": changes_asked(conn, ticket) is not None,
        "blocked": blocked,
    }


def _newest(
    conn: sqlite3.Connection,
    config: Config,
    ws: Workspace,
    plan: records.FeedbackPlan,
    now: datetime,
) -> NewestFeedbackPlan:
    waits = plan.status is PlanStatus.PROPOSED
    found = stale(conn, config, ws, plan, now) if waits else Stale(changes=(), quiet_until=None)
    return {
        "id": plan.id,
        "status": plan.status,
        "created_at": plan.created_at,
        "repos": list(repos(conn, plan)),
        "spent": plan.spent_run_id is not None,
        "stale": bool(found.changes),
        "quiet_passed": found.quiet_passed(now),
    }


def _supersede(conn: sqlite3.Connection, key: str) -> None:
    """Supersede the ticket's current feedback plan, if it has one. Call inside a transaction."""
    sql.execute(
        conn,
        sql.update("feedback_plans")
        .set(status=PlanStatus.SUPERSEDED)
        .where("ticket_key = ? AND status != ?", key, PlanStatus.SUPERSEDED),
    )
