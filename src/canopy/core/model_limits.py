"""Each model's window, as the runtime last listed it (DESIGN §13, Each agent's model).

The runtime lists each model's limits, in tokens, in the list canopy checks a run's model against before the run starts
(`canopy.core.agent_models.check`), so canopy keeps them from that read: a row per model the list gives a limit for,
replaced by each later listing. When a run's models are recorded (`canopy.core.run_models`), each takes the window its
model was last listed with, so a run's peak reads against the window it ran in rather than a later listing's. A model
run at a variant takes its model's.

Only a run on a chosen model is checked, so a model only the runtime's default runs on is kept once some check lists
it, and its runs before that have none.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import db, records
from canopy.runtime.definitions import VARIANT_RE

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable

    from canopy.runtime.report import ModelList


def keep(conn: sqlite3.Connection, listing: ModelList) -> None:
    """Keep the window of each model `listing` gives one for, in place of the one it was listed with before."""
    if not listing.limits:
        return
    now = db.now()
    columns = ("model", "input_limit", "context_limit", "listed_at")
    rows = [(model, limits.input, limits.context, now) for model, limits in sorted(listing.limits.items())]
    with db.transaction(conn):
        records.insert_rows(records.ModelLimit, columns).or_replace().many(conn, rows)


def of_models(conn: sqlite3.Connection, models: Iterable[str]) -> dict[str, records.ModelLimit]:
    """The window each of `models`, as a run's session names it, was last listed with: a variant's is its model's.

    Returns:
        Each model's window by its name, as given; a model never listed with one is not among them.
    """
    listed_as = {model: _without_variant(model) for model in models}
    if not listed_as:
        return {}
    query = records.select(records.ModelLimit).where_in("model", sorted(set(listed_as.values())))
    found = {row.model: row for row in query.all(conn)}
    return {model: found[name] for model, name in listed_as.items() if name in found}


# The model `name` names, without the variant after its last `@`, as `canopy.core.agent_models.parse` reads one.
def _without_variant(name: str) -> str:
    head, at, tail = name.rpartition("@")
    return head if at and head and VARIANT_RE.fullmatch(tail) else name
