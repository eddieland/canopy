"""The mock journal's feedback plans (DESIGN §32), for `python -m canopy.serve --mock`: one in each state a plan has.

After run 45's push, run 46 planned the next round of PR 88's feedback: alice's review and her thread to leave, since
run 45's drafts answer them, and bob's to change, the debounce made a shared constant, with the reply it would draft.
The plan waits on the operator, and is stale: carol reviewed the PR after it was written. What it saw is recorded
with it as the planner's own run records it, so the harness computes that in code, as it would for a real plan.

Every other state is on a mobile PR of its own, each its ticket's one unit (`STATES`): a plan that waits and is not
stale, one the operator approved with an item left out, one its planner approved since it changes no code, one a
`resume` spent, whose push the `vcs` source saw as checks on a new head, so the Reviews page times canopy's turnaround
on it, one that covers no review item, one whose file is gone, and one of ten items from four reviewers, a bot among
them and one with a long name. They are eight days old, so the spend pages' default week, and the counts of
what happened since a time, leave them out; the lists that show every ticket, PR, and run show them last.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import plans, records
from canopy.core.vocab import CheckConclusion, Phase, PlanStatus, Proposal, ReviewItem, ReviewState, RunKind, RunStatus
from canopy.runs import feedback_items, feedback_plans
from canopy.serve.mock.reviews import PR_88

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from canopy.core.config import Trust

RUN = 46
_KEY = "ABC-099"
_STARTED, _ENDED = -16, -12
_REVIEW = 4_102_337_001
_ALICE = 2_468_013_579
_BOB = 2_468_013_601
# carol's review, after the plan was written: what makes it stale.
_CAROL = 4_102_337_050
_TEXT = """# Feedback plan: ABC-099

The round after run 45's push to acme/web#88: alice's review and its two threads. Run 45 already drafted a reply to
each; they wait on you, and this plan changes none of them but bob's.

## Items

### Item 4102337001: leave

alice's review asks for changes; its threads are the work, below. Nothing to do for the review itself.

### Item 2468013579: leave

Run 45 moved `setLoading(false)` into a `finally`, skipped for an aborted request. Its draft says so.

### Item 2468013601: change

bob asks why 250 ms when the other inputs debounce at 300. Keep 250, which the ticket asks for, and move it into
`SEARCH_DEBOUNCE_MS` in `src/search/constants.ts`, so the inputs stop drifting apart.

## Checks

No check has run at the head yet.
"""
_ITEMS = (
    # item, id, proposal, reply
    (ReviewItem.REVIEW, _REVIEW, Proposal.LEAVE, None),
    (ReviewItem.COMMENT, _ALICE, Proposal.LEAVE, None),
    (
        ReviewItem.COMMENT,
        _BOB,
        Proposal.CHANGE,
        "Kept 250 ms, which ABC-099 asks for, and moved it into `SEARCH_DEBOUNCE_MS` so the inputs stop drifting.",
    ),
)
_DAY = 24 * 60
#: How long a state's plan run ran, in minutes.
_PLANNING = 6
#: How long the `resume` that spent a state's plan ran, in minutes.
_RESUMING = 22
#: How long after that `resume` ended its push's checks were observed, in minutes.
_CHECKING = 4
#: The checks a spent state's push ran, each passing.
_PUSH_CHECKS = ("lint", "ios-unit")
#: The reviewer with the longest name GitHub allows but one, for the stress case's rows.
LONG_AUTHOR = "maximiliana-vanderberghe-okonkwo-smith"


@dataclass(frozen=True)
class _Said:
    """A review or review comment on a state's PR, as the reader observed it: a review unless it is on a thread."""

    id: int
    author: str
    #: When it was made, in minutes before its plan's run started.
    before: int
    body: str
    #: A review's state; None for a comment.
    state: ReviewState | None = None
    #: A comment's thread, file, line, and review; None for a review.
    thread: str | None = None
    path: str | None = None
    line: int | None = None
    review: int | None = None
    bot: bool = False


@dataclass(frozen=True)
class _Item:
    """An item a state's plan covers, by the id of what was said, with what it proposes and the reply it would draft."""

    said: int
    proposal: Proposal
    reply: str | None = None


@dataclass(frozen=True)
class _Approval:
    """How a state's plan was approved: by the operator on a channel, or by its planner, saying why."""

    channel: str
    #: Minutes after the plan was written.
    after: int
    #: The numbers of the items it left out.
    left: Sequence[int] = ()
    #: The operator's own words after the message it wrote; None for none.
    words: str | None = None
    #: The planner's reason, for its approval; None for the operator's, which writes a message.
    reason: str | None = None


@dataclass(frozen=True)
class _State:
    """A feedback plan's state, seeded on a ticket and a mobile PR of its own."""

    key: str
    title: str
    #: The ticket's branch, after `agent/<key>-`.
    slug: str
    number: int
    phase: Phase
    #: Its plan's run; the `resume` that spent it, when one did, is the run after.
    run: int
    #: When its plan's run started, in minutes from T0.
    start: int
    said: Sequence[_Said]
    items: Sequence[_Item]
    text: str
    summary: str
    #: A check at the PR's head that failed, by name.
    failed: str | None = None
    approval: _Approval | None = None
    #: The summary of the `resume` that went ahead on it, when one did.
    spent: str | None = None
    #: Whether its file was removed after it was written.
    gone: bool = False

    @property
    def url(self) -> str:
        """The state's PR."""
        return f"https://github.com/acme/mobile/pull/{self.number}"

    @property
    def written(self) -> int:
        """When its plan's run ended, its plan written, in minutes from T0."""
        return self.start + _PLANNING

    @property
    def approved(self) -> int:
        """When its plan was approved, in minutes from T0; when it was written, for one not approved."""
        return self.written + (self.approval.after if self.approval is not None else 0)

    @property
    def resumed(self) -> int:
        """When the `resume` that spent its plan started, in minutes from T0, for a plan one spent."""
        return self.approved + 5

    @property
    def ended(self) -> int:
        """When its story ends, in minutes from T0: its plan written, approved, or spent by a `resume` that ended."""
        return self.resumed + _RESUMING if self.spent is not None else self.approved


_SPENT = _State(
    key="ABC-130",
    title="Retry failed push notifications",
    slug="push-retry",
    number=61,
    phase=Phase.REVIEW_PENDING,
    run=50,
    start=-8 * _DAY - 420,
    said=(
        _Said(4_102_500_101, "dana", 50, "One retry is not a policy.", state=ReviewState.CHANGES_REQUESTED),
        _Said(
            2_468_500_201,
            "dana",
            50,
            "Back off between tries, and stop after three: a dead token retried forever drains the battery.",
            thread="PRRT_kwDOM61a",
            path="app/notify/push.ts",
            line=27,
            review=4_102_500_101,
        ),
    ),
    items=(
        _Item(4_102_500_101, Proposal.LEAVE),
        _Item(
            2_468_500_201,
            Proposal.CHANGE,
            "Push sends back off now, doubling from a second, and stop after the third try.",
        ),
    ),
    text="""# Feedback plan: ABC-130

dana's review of acme/mobile#61 and its one thread.

## Items

### Item 4102500101: leave

The review's work is its thread, below.

### Item 2468500201: change

Wrap `sendPush` in a backoff, doubling from one second, and stop after three tries.

## Checks

Every check passed at the head.
""",
    summary="Planned the round on PR 61: change dana's thread, a backoff with three tries at most.",
    approval=_Approval(channel="cli", after=12),
    spent="Push sends back off now, three tries at most, and the reply to dana says so.",
)
_BY_THE_PLANNER = _State(
    key="ABC-131",
    title="Rename the billing settings tab",
    slug="billing-tab",
    number=62,
    phase=Phase.REVIEW_PENDING,
    run=52,
    start=-8 * _DAY - 360,
    said=(
        _Said(4_102_500_102, "gina", 30, "Reads fine. Two thoughts, neither blocking.", state=ReviewState.COMMENTED),
        _Said(
            2_468_500_202,
            "gina",
            30,
            "Would `Payments` be clearer than `Billing`?",
            thread="PRRT_kwDOM62a",
            path="app/settings/tabs.ts",
            line=14,
            review=4_102_500_102,
        ),
        _Said(
            2_468_500_203,
            "frank",
            20,
            "Is the old route still linked from anywhere?",
            thread="PRRT_kwDOM62b",
            path="app/settings/BillingTab.tsx",
            line=5,
        ),
    ),
    items=(
        _Item(4_102_500_102, Proposal.LEAVE),
        _Item(
            2_468_500_202,
            Proposal.DECLINE,
            "Billing is the ticket's word and the help center's; renaming it again is a ticket of its own.",
        ),
        _Item(2_468_500_203, Proposal.ASK),
    ),
    text="""# Feedback plan: ABC-131

gina's review of acme/mobile#62 and frank's question. Nothing here changes code.

## Items

### Item 4102500102: leave

A comment, not a request.

### Item 2468500202: decline

The ticket names the tab Billing, and so does the help center.

### Item 2468500203: ask

Whether a push notification still deep-links to the old route: ask frank which one he means.

## Checks

Every check passed at the head.
""",
    summary="Planned the round on PR 62: decline gina's rename, ask frank about the old route. It changes no code.",
    approval=_Approval(
        channel=plans.PLANNER,
        after=0,
        reason="every item is a decline, an ask, or a leave: it changes no code, and its replies wait on you",
    ),
)
_LEFT_OUT = _State(
    key="ABC-132",
    title="Paginate the order history",
    slug="order-history",
    number=63,
    phase=Phase.CHANGES_REQUESTED,
    run=53,
    start=-8 * _DAY - 300,
    said=(
        _Said(
            4_102_500_103,
            "erin",
            40,
            "The list loads every order at once; that is the bug report.",
            state=ReviewState.CHANGES_REQUESTED,
        ),
        _Said(
            2_468_500_204,
            "erin",
            40,
            "Page it, 25 at a time, from the list's own `onEndReached`.",
            thread="PRRT_kwDOM63a",
            path="app/orders/OrderList.tsx",
            line=31,
            review=4_102_500_103,
        ),
        _Said(
            2_468_500_205,
            "frank",
            25,
            "Cursor instead of offset? Offsets skip a row when an order lands mid-scroll.",
            thread="PRRT_kwDOM63b",
            path="app/orders/useOrders.ts",
            line=9,
        ),
    ),
    items=(
        _Item(4_102_500_103, Proposal.LEAVE),
        _Item(
            2_468_500_204,
            Proposal.CHANGE,
            "Pages of 25 now, the next one fetched from `onEndReached`.",
        ),
        _Item(2_468_500_205, Proposal.ASK),
    ),
    text="""# Feedback plan: ABC-132

erin's review of acme/mobile#63 and frank's thread.

## Items

### Item 4102500103: leave

The review's work is its thread, below.

### Item 2468500204: change

Fetch 25 orders a page, the next from `onEndReached`, with a spinner at the foot while it loads.

### Item 2468500205: ask

A cursor needs the API to sort by a stable key: ask whether `/orders` takes `after`.

## Checks

Every check passed at the head.
""",
    summary="Planned the round on PR 63: change erin's thread to page the list, ask about frank's cursor.",
    approval=_Approval(
        channel="web",
        after=25,
        left=(3,),
        words="Keep the offsets for now; cursors can have a ticket of their own.",
    ),
)
_GONE = _State(
    key="ABC-133",
    title="Drop the legacy coupon codes",
    slug="coupons",
    number=64,
    phase=Phase.REVIEW_PENDING,
    run=54,
    start=-8 * _DAY - 240,
    said=(
        _Said(4_102_500_104, "gina", 30, "Two questions, nothing blocking.", state=ReviewState.COMMENTED),
        _Said(
            2_468_500_206,
            "gina",
            30,
            "Should an old code get a friendly error rather than `invalid`?",
            thread="PRRT_kwDOM64a",
            path="app/coupons/redeem.ts",
            line=22,
            review=4_102_500_104,
        ),
    ),
    items=(
        _Item(4_102_500_104, Proposal.LEAVE),
        _Item(2_468_500_206, Proposal.CHANGE, "An old code says it has expired now, and names the new ones."),
    ),
    text="""# Feedback plan: ABC-133

gina's review of acme/mobile#64 and its thread.

## Items

### Item 4102500104: leave

### Item 2468500206: change

Say an old code has expired, rather than `invalid`.
""",
    summary="Planned the round on PR 64: change gina's thread, a friendlier error for an old code.",
    gone=True,
)
_NO_ITEMS = _State(
    key="ABC-134",
    title="Cache product images for offline browsing",
    slug="image-cache",
    number=65,
    phase=Phase.CI_RED,
    run=55,
    start=-8 * _DAY - 180,
    said=(),
    items=(),
    text="""# Feedback plan: ABC-134

No review came back on acme/mobile#65. Its one failed check is the round.

## Items

None.

## Checks

### ios-unit: failure

`ImageCacheTests.testEvictsOldest` expects 50 entries, and the cache holds 64 now, as the ticket asks. Bound the test
by `MAX_ENTRIES` rather than a number of its own, and leave the cache as it is.
""",
    summary="Planned the round on PR 65: no review item, and ios-unit's failure, a test bound to the old size.",
    failed="ios-unit",
)
_STRESS = _State(
    key="ABC-135",
    title="Move the checkout to the new payments SDK",
    slug="payments-sdk",
    number=66,
    phase=Phase.CHANGES_REQUESTED,
    run=56,
    start=-8 * _DAY - 120,
    said=(
        _Said(
            4_102_500_105,
            LONG_AUTHOR,
            90,
            "Thanks for taking this on. A few things before it goes in; the 3DS flow is the one I care about most.",
            state=ReviewState.CHANGES_REQUESTED,
        ),
        _Said(
            2_468_500_207,
            LONG_AUTHOR,
            90,
            "The 3DS challenge can come back after the sheet unmounts. Guard the callback, or a slow bank crashes the "
            "app.",
            thread="PRRT_kwDOM66a",
            path="app/checkout/PaymentSheet.tsx",
            line=42,
            review=4_102_500_105,
        ),
        _Said(
            2_468_500_208,
            "op",
            70,
            "Is that reachable? The sheet stays mounted until the promise settles.",
            thread="PRRT_kwDOM66a",
            path="app/checkout/PaymentSheet.tsx",
            line=42,
        ),
        _Said(
            2_468_500_209,
            LONG_AUTHOR,
            60,
            "It is on Android when the app is backgrounded mid-challenge. I hit it twice yesterday.",
            thread="PRRT_kwDOM66a",
            path="app/checkout/PaymentSheet.tsx",
            line=42,
        ),
        _Said(
            2_468_500_210,
            LONG_AUTHOR,
            90,
            "Please don't log the whole intent: it carries the customer's email.",
            thread="PRRT_kwDOM66b",
            path="app/checkout/PaymentSheet.tsx",
            line=77,
            review=4_102_500_105,
        ),
        _Said(
            2_468_500_211,
            LONG_AUTHOR,
            90,
            "Why not keep the old SDK behind a flag for one release?",
            thread="PRRT_kwDOM66c",
            path="app/checkout/useCheckout.ts",
            line=12,
            review=4_102_500_105,
        ),
        _Said(
            4_102_500_106,
            "lint-bot",
            85,
            "2 warnings: an unused import in `app/checkout/legacy.ts`, and a function with no return type.",
            state=ReviewState.COMMENTED,
            bot=True,
        ),
        _Said(
            2_468_500_212,
            "lint-bot",
            85,
            "`formatAmount` is imported but never used.",
            thread="PRRT_kwDOM66d",
            path="app/checkout/legacy.ts",
            line=3,
            review=4_102_500_106,
            bot=True,
        ),
        _Said(
            4_102_500_107,
            "erin",
            50,
            "Does this change the receipts at all? Finance reconciles on the old intent ids.",
            state=ReviewState.COMMENTED,
        ),
        _Said(
            2_468_500_213,
            "erin",
            50,
            "This drops `legacy_intent_id` from the receipt's payload.",
            thread="PRRT_kwDOM66e",
            path="app/checkout/receipt.ts",
            line=30,
            review=4_102_500_107,
        ),
        _Said(
            2_468_500_214,
            "frank",
            40,
            "nit: `isLoading` to `loading`, like the rest of the app.",
            thread="PRRT_kwDOM66f",
            path="app/checkout/PaymentSheet.tsx",
            line=120,
        ),
        _Said(
            2_468_500_215,
            "frank",
            35,
            "Could the test cover a declined card too?",
            thread="PRRT_kwDOM66g",
            path="app/checkout/__tests__/PaymentSheet.test.tsx",
            line=8,
        ),
    ),
    items=(
        _Item(4_102_500_105, Proposal.LEAVE),
        _Item(
            2_468_500_207,
            Proposal.CHANGE,
            "Guarded: the challenge's callback checks the sheet is still mounted, and a result that comes back after "
            "it closed is kept for the order screen rather than dropped. Reproduced on Android by backgrounding the "
            "app mid-challenge, as you said.",
        ),
        _Item(2_468_500_210, Proposal.CHANGE, "It logs the intent's id and status now, and nothing of the customer's."),
        _Item(
            2_468_500_211,
            Proposal.DECLINE,
            "The old SDK stops taking payments at the end of the month, so a flag would only keep a dead path alive "
            "for a release.",
        ),
        _Item(4_102_500_106, Proposal.CHANGE, "Both fixed."),
        _Item(2_468_500_212, Proposal.CHANGE),
        _Item(4_102_500_107, Proposal.ASK),
        _Item(
            2_468_500_213,
            Proposal.CHANGE,
            "Kept `legacy_intent_id` in the payload, filled from the new intent's metadata, so reconciliation reads it "
            "as before.",
        ),
        _Item(
            2_468_500_214,
            Proposal.DECLINE,
            "The SDK's own hook names it `isLoading`; matching it keeps the adapter thin.",
        ),
        _Item(2_468_500_215, Proposal.CHANGE, "Added a declined card, and an expired one while I was there."),
    ),
    text=f"""# Feedback plan: ABC-135

The first round on acme/mobile#66: three reviews, seven threads, and a failed check. {LONG_AUTHOR}'s 3DS thread is
the one that matters; the rest are small.

## Items

### Item 4102500105: leave

The review's work is its threads, below.

### Item 2468500207: change

The thread's replies settle it: the crash is real on Android, backgrounded mid-challenge. Guard the callback with the
sheet's mounted ref, and hand a late result to the order screen.

### Item 2468500210: change

Log `intent.id` and `intent.status` only.

### Item 2468500211: decline

The old SDK stops taking payments at the end of the month.

### Item 4102500106: change

lint-bot's two warnings: the unused import, below, and a return type on `toMinorUnits`.

### Item 2468500212: change

Remove the import.

### Item 4102500107: ask

Ask finance which ids the reconciliation reads besides `legacy_intent_id`.

### Item 2468500213: change

Fill `legacy_intent_id` from the new intent's metadata.

### Item 2468500214: decline

The SDK's hook names it `isLoading`.

### Item 2468500215: change

Add a declined card and an expired one to `PaymentSheet.test.tsx`.

## Checks

### android-e2e: failure

`checkout.3ds.e2e` times out on the emulator: the crash item 2468500207 fixes, behind it.
""",
    summary="Planned the round on PR 66: ten items, six to change, two to decline, one to ask about, one to leave.",
    failed="android-e2e",
)
_WAITING = _State(
    key="ABC-136",
    title="Show the cart's total before tax",
    slug="cart-total",
    number=67,
    phase=Phase.CHANGES_REQUESTED,
    run=57,
    start=-8 * _DAY - 60,
    said=(
        _Said(
            4_102_500_108,
            "dana",
            30,
            "Close. The total needs to say it is before tax, or support will hear about it.",
            state=ReviewState.CHANGES_REQUESTED,
        ),
        _Said(
            2_468_500_216,
            "dana",
            30,
            "Label this `Subtotal (before tax)`: `Total` reads as what the card is charged.",
            thread="PRRT_kwDOM67a",
            path="app/cart/CartTotal.tsx",
            line=18,
            review=4_102_500_108,
        ),
    ),
    items=(
        _Item(4_102_500_108, Proposal.LEAVE),
        _Item(
            2_468_500_216,
            Proposal.CHANGE,
            "Renamed the label to `Subtotal (before tax)`, and its accessibility label says the same.",
        ),
    ),
    text="""# Feedback plan: ABC-136

dana's review of acme/mobile#67 and its thread.

## Items

### Item 4102500108: leave

The review's work is its thread, below.

### Item 2468500216: change

Rename the label in `CartTotal.tsx` and its accessibility label to `Subtotal (before tax)`.

## Checks

Every check passed at the head.
""",
    summary="Planned the round on PR 67: change dana's thread, the total's label.",
)
#: Each state but PR 88's stale one, by its name, and the PR whose page shows it.
STATES: Mapping[str, _State] = {
    "waiting": _WAITING,
    "approved": _LEFT_OUT,
    "approved-by-planner": _BY_THE_PLANNER,
    "spent": _SPENT,
    "no-items": _NO_ITEMS,
    "missing": _GONE,
    "many-items": _STRESS,
}


def seed(conn: sqlite3.Connection, state_dir: Path, at: Callable[[int], str], trust: Trust, slot: str) -> None:
    """Insert run 46, in web's `slot`, its plan, waiting, its file and what it saw of PR 88, then bob's reply."""
    log_path = state_dir / "runs" / f"{RUN}.log"
    result = {"status": "done", "summary": "Planned PR 88's next round: leave alice's two items, change bob's."}
    records.insert(
        records.Run,
        id=RUN,
        tick_id=1,
        ticket_key=_KEY,
        kind=RunKind.FEEDBACK_PLAN,
        branch="agent/ABC-099-search",
        started_at=at(_STARTED),
        ended_at=at(_ENDED),
        status=RunStatus.DONE,
        result_json=json.dumps(result),
        log_path=str(log_path),
        private=0,
    ).run(conn)
    records.insert(
        records.RunSlot,
        run_id=RUN,
        repo="web",
        slot_path=slot,
        lease_id="lease-46",
        lease_holder="canopy:ABC-099",
        base_branch="main",
    ).run(conn)
    written = plans.write(state_dir, _KEY, RUN, _TEXT)
    [plan_id] = (
        records.insert(
            records.FeedbackPlan,
            ticket_key=_KEY,
            run_id=RUN,
            created_at=at(_ENDED),
            status=PlanStatus.PROPOSED,
            sha256=written.sha256,
            size=written.size,
        )
        .returning("id")
        .run(conn)
        .fetchone()
    )
    records.insert_rows(
        records.FeedbackPlanItem,
        ("plan_id", "number", "pr_url", "item", "item_id", "proposal", "reply"),
    ).many(conn, [(plan_id, n, PR_88, *item) for n, item in enumerate(_ITEMS, start=1)])
    given = feedback_items.offered(conn, trust, _KEY, [PR_88])
    feedback_items.record(conn, plan_id, feedback_items.take(conn, [PR_88], given, {}))
    _review(conn, at)


def seed_states(
    conn: sqlite3.Connection,
    state_dir: Path,
    at: Callable[[int], str],
    trust: Trust,
    *,
    repo: str,
    slot: str,
) -> None:
    """Insert each of `STATES`: its ticket of `repo`, the workspace, its PR as last read, and its plan's run and plan.

    Each plan's run ran in mobile's `slot`, and its plan is recorded as the planner's run records one, what it saw of
    its PR with it, then approved, spent, or its file removed as its state says.
    """
    for state in STATES.values():
        _ticket(conn, at, state, repo)
        _read(conn, at, state)
        _plan(conn, state_dir, at, trust, state, slot=slot)


def _review(conn: sqlite3.Connection, at: Callable[[int], str]) -> None:
    """The review carol left, as the reader's next whole read of PR 88 holds it, with all else it read again."""
    read_at = at(-5)
    records.update(records.ObservedPr).set(observed_at=read_at).where("url = ?", PR_88).run(conn)
    records.update(records.ObservedReview).set(observed_at=read_at).where("pr_url = ?", PR_88).run(conn)
    records.insert(
        records.ObservedReview,
        pr_url=PR_88,
        item="review",
        id=_CAROL,
        author="carol",
        bot=0,
        state="commented",
        created_at=at(-6),
        body="Fine by me once the debounce is a shared constant; the filters could use it too.",
        url=f"{PR_88}#pullrequestreview-{_CAROL}",
        observed_at=read_at,
    ).run(conn)


def _ticket(conn: sqlite3.Connection, at: Callable[[int], str], state: _State, repo: str) -> None:
    """The state's ticket, its one unit, in mobile, on its PR, and the PR's title, last changed when its story ends."""
    branch = f"agent/{state.key}-{state.slug}"
    records.insert(
        records.Ticket,
        key=state.key,
        repo=repo,
        first_seen_at=at(state.start - _DAY),
        last_seen_at=at(state.ended),
        changed_at=at(state.ended),
        title=state.title,
        phase=state.phase,
        branch=branch,
    ).run(conn)
    records.insert(
        records.TicketUnit,
        ticket_key=state.key,
        repo="mobile",
        branch=branch,
        pr_url=state.url,
        phase=state.phase,
    ).run(conn)
    title = f"{state.key}: {state.title[0].lower()}{state.title[1:]}"
    records.insert(records.PrTitle, pr_url=state.url, title=title, updated_at=at(state.start - _DAY)).run(conn)


def _read(conn: sqlite3.Connection, at: Callable[[int], str], state: _State) -> None:
    """The reader's last whole read of the state's PR, before its plan ran: the PR, what was said, its failed check."""
    read_at = at(state.start - 5)
    head = f"{state.number:02d}" * 20
    records.insert(
        records.ObservedPr,
        url=state.url,
        repository="acme/mobile",
        number=state.number,
        head_sha=head,
        base_ref="main",
        state="open",
        draft=0,
        mergeable="mergeable",
        author="op",
        title=state.title,
        observed_at=read_at,
    ).run(conn)
    for said in state.said:
        kind = ReviewItem.REVIEW if said.thread is None else ReviewItem.COMMENT
        anchor = f"pullrequestreview-{said.id}" if said.thread is None else f"discussion_r{said.id}"
        records.insert(
            records.ObservedReview,
            pr_url=state.url,
            item=kind,
            id=said.id,
            author=said.author,
            bot=int(said.bot),
            state=said.state,
            created_at=at(state.start - said.before),
            body=said.body,
            url=f"{state.url}#{anchor}",
            review_id=said.review,
            thread_id=said.thread,
            path=said.path,
            line=said.line,
            side=None if said.thread is None else "right",
            outdated=None if said.thread is None else 0,
            resolved=None if said.thread is None else 0,
            observed_at=read_at,
        ).run(conn)
    if state.failed is not None:
        records.insert(
            records.ObservedCheck,
            pr_url=state.url,
            name=state.failed,
            head_sha=head,
            status="completed",
            conclusion="failure",
            run_id=9_100_000 + state.number,
            url=f"https://github.com/acme/mobile/actions/runs/{9_100_000 + state.number}",
            observed_at=read_at,
        ).run(conn)


def _plan(
    conn: sqlite3.Connection,
    state_dir: Path,
    at: Callable[[int], str],
    trust: Trust,
    state: _State,
    *,
    slot: str,
) -> None:
    """The state's plan run, its plan and what it saw, then its approval, its `resume`, or its file removed."""
    _run(
        conn,
        state_dir,
        state,
        run=state.run,
        kind=RunKind.FEEDBACK_PLAN,
        span=(at(state.start), at(state.written)),
        result={"status": "done", "summary": state.summary},
        slot=slot,
    )
    written = plans.write(state_dir, state.key, state.run, state.text)
    [plan_id] = (
        records.insert(
            records.FeedbackPlan,
            ticket_key=state.key,
            run_id=state.run,
            created_at=at(state.written),
            status=PlanStatus.PROPOSED,
            sha256=written.sha256,
            size=written.size,
        )
        .returning("id")
        .run(conn)
        .fetchone()
    )
    kinds = {s.id: ReviewItem.REVIEW if s.thread is None else ReviewItem.COMMENT for s in state.said}
    records.insert_rows(
        records.FeedbackPlanItem,
        ("plan_id", "number", "pr_url", "item", "item_id", "proposal", "reply"),
    ).many(
        conn,
        [
            (plan_id, n, state.url, kinds[i.said], i.said, i.proposal, i.reply)
            for n, i in enumerate(state.items, start=1)
        ],
    )
    given = feedback_items.offered(conn, trust, state.key, [state.url])
    feedback_items.record(conn, plan_id, feedback_items.take(conn, [state.url], given, {}))
    if state.approval is not None:
        _approve(conn, state, plan_id, written.sha256, at(state.approved))
    if state.spent is not None:
        _spend(conn, state_dir, at, state, plan_id, slot=slot)
    if state.gone:
        plans.path_for(state_dir, state.key, state.run).unlink()


def _approve(
    conn: sqlite3.Connection,
    state: _State,
    plan_id: int,
    sha256: str,
    when: str,
) -> None:
    """Approve the state's plan as `feedback_plans.approve` does, with the message it writes, or as its planner's."""
    approval = state.approval
    assert approval is not None  # noqa: S101  (only a state with an approval is approved)
    message: int | None = None
    if approval.reason is None:
        named = [(n, i.said) for n, i in enumerate(state.items, start=1)]
        body = feedback_plans.approval_message(
            plan_id,
            [i for i in named if i[0] not in approval.left],
            [i for i in named if i[0] in approval.left],
            approval.words,
        )
        message = (
            records.insert(
                records.Message,
                subject_kind="ticket",
                subject_id=state.key,
                at=when,
                source="operator",
                kind="reply",
                channel=approval.channel,
                body=body,
                submission=f"feedback-plan/{plan_id}/after/0",
            )
            .run(conn)
            .lastrowid
        )
    if approval.left:
        (
            records.update(records.FeedbackPlanItem)
            .set(left_out=True)
            .where("plan_id = ?", plan_id)
            .where_in("number", approval.left)
            .run(conn)
        )
    (
        records.update(records.FeedbackPlan)
        .set(
            status=PlanStatus.APPROVED,
            approved_sha256=sha256,
            approved_at=when,
            approved_channel=approval.channel,
            approved_reason=approval.reason,
            approved_message_id=message,
        )
        .where("id = ?", plan_id)
        .run(conn)
    )


def _spend(
    conn: sqlite3.Connection,
    state_dir: Path,
    at: Callable[[int], str],
    state: _State,
    plan_id: int,
    *,
    slot: str,
) -> None:
    """The `resume` that went ahead on the state's approved plan, the run after its plan's, which spent it.

    Its push is the checks a `vcs` source observed passing on the PR's next head, soon after it ended: the push that
    answered the round.
    """
    run = state.run + 1
    _run(
        conn,
        state_dir,
        state,
        run=run,
        kind=RunKind.RESUME,
        span=(at(state.resumed), at(state.ended)),
        result={"summary": state.spent, "prs": {"mobile": state.url}},
        slot=slot,
    )
    records.insert(records.RunReason, run_id=run, reason="review").run(conn)
    records.update(records.FeedbackPlan).set(spent_run_id=run).where("id = ?", plan_id).run(conn)
    pushed = f"{state.number:02d}a" * 13 + "a"
    records.insert_rows(
        records.ObservedCheckRun,
        ("pr_url", "run_id", "name", "head_sha", "conclusion", "observed_at"),
    ).many(
        conn,
        [
            (
                state.url,
                9_300_000 + 10 * state.number + i,
                name,
                pushed,
                CheckConclusion.SUCCESS,
                at(state.ended + _CHECKING),
            )
            for i, name in enumerate(_PUSH_CHECKS)
        ],
    )


def _run(
    conn: sqlite3.Connection,
    state_dir: Path,
    state: _State,
    *,
    run: int,
    kind: RunKind,
    span: tuple[str, str],
    result: Mapping[str, object],
    slot: str,
) -> None:
    """A run of the state's ticket that ended `done`, in mobile's `slot`; no session named it, so it has no cost."""
    records.insert(
        records.Run,
        id=run,
        tick_id=1,
        ticket_key=state.key,
        kind=kind,
        branch=f"agent/{state.key}-{state.slug}",
        started_at=span[0],
        ended_at=span[1],
        status=RunStatus.DONE,
        result_json=json.dumps(result),
        log_path=str(state_dir / "runs" / f"{run}.log"),
        private=0,
    ).run(conn)
    records.insert(
        records.RunSlot,
        run_id=run,
        repo="mobile",
        slot_path=slot,
        lease_id=f"lease-{run}",
        lease_holder=f"canopy:{state.key}",
        base_branch="main",
    ).run(conn)
