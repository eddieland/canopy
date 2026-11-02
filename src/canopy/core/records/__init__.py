"""The journal's tables: a row type per table, a frozen dataclass whose fields are its columns, in order.

`tests/canopy/core/test_records.py` checks every row type against its table after every migration: the same columns,
in order, each with the type and nullability its column has, so a migration that adds a column adds its field to its
row type. A column holding one of `vocab`'s closed vocabularies is a field of that `StrEnum`, and a flag column a
`bool`.

Each domain's tables are a module of this package, such as `records.runs` or `records.reviews`, and a new table goes
in its domain's. A row type is read and written through `orm`, whose docstring says how rows are checked and converted.
Every table and every name of `orm` is re-exported here, so a caller names a table and its query from one module:

    running = records.select(records.Run).where("status = ?", RunStatus.RUNNING).order_by("id").all(conn)
    records.insert(records.Tick, started_at=now, status=TickStatus.RUNNING, dry_run=True).run(conn)
"""

from __future__ import annotations

import functools
from collections.abc import Mapping
from typing import LiteralString

from canopy.core.orm import (
    Delete,
    Insert,
    Query,
    Record,
    Row,
    RowError,
    Update,
    View,
    columns,
    delete,
    fetch_all,
    fetch_one,
    insert,
    insert_from,
    insert_rows,
    select,
    update,
)
from canopy.core.records.agents import (
    NextRunPersona,
    PersonaText,
    RunModel,
    RunModelRead,
    RunOffer,
    RunOfferedServer,
    RunOfferedServerRule,
    RunOfferedSkill,
    RunOfferedTool,
    RunReplyModel,
    RuntimeSession,
    RuntimeSessionModel,
    RuntimeSessionRead,
    RunTool,
    TicketOverride,
)
from canopy.core.records.chores import (
    ChoreRun,
    FindingDismissal,
)
from canopy.core.records.controls import (
    Attachment,
    AttemptGrant,
    Forget,
    Message,
    Notice,
    Pause,
    Seen,
    Start,
    TicketGrant,
    WebWrite,
)
from canopy.core.records.drafts import (
    Draft,
    DraftVersion,
    RunReplies,
)
from canopy.core.records.memory import (
    Memory,
    MemoryRead,
    RunMemory,
)
from canopy.core.records.notify import (
    Notification,
    NotifyEvent,
    NotifySink,
)
from canopy.core.records.observed import (
    ConnectorRun,
    ItemNumber,
    ObservedArtifactComment,
    ObservedArtifactThread,
    ObservedBranch,
    ObservedCheck,
    ObservedCheckRun,
    ObservedComment,
    ObservedFeed,
    ObservedPr,
    ObservedReview,
    ObservedTicket,
    PrTitle,
)
from canopy.core.records.plans import (
    FeedbackPlan,
    FeedbackPlanCheck,
    FeedbackPlanItem,
    FeedbackPlanMove,
    FeedbackPlanPr,
    FeedbackPlanSeen,
    Plan,
    PlanMetric,
    PlanReply,
    PlanThread,
    PlanWaiver,
)
from canopy.core.records.reviews import (
    ReviewAnswer,
    ReviewDismissal,
    ReviewDraft,
    ReviewDraftGrant,
    ReviewDraftNote,
    ReviewDraftVersion,
    ReviewGrant,
    ReviewHead,
    ReviewHold,
    ReviewRequest,
    ReviewRequestPersona,
    ReviewRun,
)
from canopy.core.records.runs import (
    ChecklistAnswer,
    FlakyKick,
    PoolSlot,
    Run,
    RunRead,
    RunReason,
    RunSlot,
)
from canopy.core.records.tasks import (
    Task,
    TaskRun,
    TaskTicket,
)
from canopy.core.records.tickets import (
    FollowUp,
    SplitChild,
    Ticket,
    TicketUnit,
)
from canopy.core.records.ticks import (
    Decision,
    Derivation,
    GcPass,
    OverseerRun,
    RecordedRun,
    Tick,
)

# Kept importable from here: callers name a table and its query from one module, as `records.select(records.Run)`.
__all__ = [
    "Attachment",
    "AttemptGrant",
    "ChecklistAnswer",
    "ChoreRun",
    "ConnectorRun",
    "Decision",
    "Delete",
    "Derivation",
    "Draft",
    "DraftVersion",
    "FeedbackPlan",
    "FeedbackPlanCheck",
    "FeedbackPlanItem",
    "FeedbackPlanMove",
    "FeedbackPlanPr",
    "FeedbackPlanSeen",
    "FindingDismissal",
    "FlakyKick",
    "FollowUp",
    "Forget",
    "GcPass",
    "Insert",
    "ItemNumber",
    "Memory",
    "MemoryRead",
    "Message",
    "NextRunPersona",
    "Notice",
    "Notification",
    "NotifyEvent",
    "NotifySink",
    "ObservedArtifactComment",
    "ObservedArtifactThread",
    "ObservedBranch",
    "ObservedCheck",
    "ObservedCheckRun",
    "ObservedComment",
    "ObservedFeed",
    "ObservedPr",
    "ObservedReview",
    "ObservedTicket",
    "OverseerRun",
    "Pause",
    "PersonaText",
    "Plan",
    "PlanMetric",
    "PlanReply",
    "PlanThread",
    "PlanWaiver",
    "PoolSlot",
    "PrTitle",
    "Query",
    "Record",
    "RecordedRun",
    "ReviewAnswer",
    "ReviewDismissal",
    "ReviewDraft",
    "ReviewDraftGrant",
    "ReviewDraftNote",
    "ReviewDraftVersion",
    "ReviewGrant",
    "ReviewHead",
    "ReviewHold",
    "ReviewRequest",
    "ReviewRequestPersona",
    "ReviewRun",
    "Row",
    "RowError",
    "Run",
    "RunMemory",
    "RunModel",
    "RunModelRead",
    "RunOffer",
    "RunOfferedServer",
    "RunOfferedServerRule",
    "RunOfferedSkill",
    "RunOfferedTool",
    "RunRead",
    "RunReason",
    "RunReplies",
    "RunReplyModel",
    "RunSlot",
    "RunTool",
    "RuntimeSession",
    "RuntimeSessionModel",
    "RuntimeSessionRead",
    "Seen",
    "SplitChild",
    "Start",
    "Task",
    "TaskRun",
    "TaskTicket",
    "Tick",
    "Ticket",
    "TicketGrant",
    "TicketOverride",
    "TicketUnit",
    "Update",
    "View",
    "WebWrite",
    "columns",
    "delete",
    "fetch_all",
    "fetch_one",
    "insert",
    "insert_from",
    "insert_rows",
    "select",
    "update",
]


def of_table(table: LiteralString) -> type[Row]:
    """The row type of the journal table named `table`, for a write to a table chosen at run time from a `Literal`.

    Returns:
        The row type.

    Raises:
        KeyError: No row type names `table`.
    """
    return _row_types()[table]


# Cached: the row types are all defined once this package is imported.
@functools.cache
def _row_types() -> Mapping[str, type[Row]]:
    """Each journal table's row type, by its table: the ones this package's modules define, not a test's own.

    Returns:
        The row types.
    """
    return {t.TABLE: t for t in Row.__subclasses__() if t.__module__.startswith(f"{__name__}.")}
