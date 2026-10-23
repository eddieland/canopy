"""Search hits as the API sends them (DESIGN §22, Search): the journal's rows holding every word of a query.

A hit's snippet is the journal's text, which may be an agent's or the tracker's, and the UI renders it as text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import db, search
from canopy.serve.schema.search import SearchHit, SearchResults

if TYPE_CHECKING:
    from canopy.core.context import Context


def found(ctx: Context, query: str) -> SearchResults:
    """The journal's rows holding every word of `query` (DESIGN §22, Search). Raises search.BadQueryError.

    Returns:
        The words searched for, the hits, and the sources that had more hits than were read.
    """
    result = search.search(ctx.conn, query)
    return SearchResults(
        words=list(result.words),
        hits=[
            SearchHit(
                source=h.source,
                at=db.parse_time(h.at),
                snippet=h.snippet,
                ticket_key=h.ticket_key,
                chore=h.chore,
                task_id=h.task_id,
                task_title=h.task_title,
                run_id=h.run_id,
                tick_id=h.tick_id,
                label=h.label,
            )
            for h in result.hits
        ],
        more=list(result.more),
    )
