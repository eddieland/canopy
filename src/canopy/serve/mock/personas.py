"""The personas the mock journal's runs and reviews wrote in (DESIGN §31), for `python -m canopy.serve --mock`.

canopy's own, but ABC-099's reviewer, whom the operator set to `skeptic` from its page before its latest review, and
the second of the two personas the operator asked Carol's PR to be reviewed in.
ABC-105's newest plan run read canopy's text as it ships; the rest, made-up digests, each kept with its text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import db, personas, records
from canopy.core.vocab import OverrideKind, RunKind

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

    from canopy.core import config

#: The made-up digests of the personas runs and reviews wrote in.
_CANOPY_DIGEST = "c4a0f1e2d3b4a5968778695a4b3c2d1e0f1a2b3c4d5e6f708192a3b4c5d6e7f8"
_SKEPTIC_DIGEST = "5e7a1c2b3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8"


def seed(conn: sqlite3.Connection, cfg: config.Config, at: Callable[[int], str]) -> None:
    """Set the persona each run and review wrote in, keep each digest's text, and record ABC-099's override."""
    (
        records.update(records.Run)
        .set(persona="canopy", persona_digest=_CANOPY_DIGEST)
        .where_in("kind", [RunKind.IMPLEMENT, RunKind.RESUME, RunKind.PLAN])
        .run(conn)
    )
    canopy, skeptic = personas.load(cfg, personas.DEFAULT), personas.load(cfg, "skeptic")
    records.update(records.Run).set(persona_digest=canopy.digest).where("id = 44").run(conn)
    for digest, text in ((canopy.digest, canopy.text), (_CANOPY_DIGEST, canopy.text), (_SKEPTIC_DIGEST, skeptic.text)):
        db.record_persona_text(conn, digest, text)
    records.update(records.ReviewRun).set(persona="canopy", persona_digest=_CANOPY_DIGEST).everything().run(conn)
    (
        records.update(records.ReviewRun)
        .set(persona="skeptic", persona_digest=_SKEPTIC_DIGEST)
        .where_in("id", [4, 6])
        .run(conn)
    )
    records.insert(
        records.TicketOverride,
        ticket_key="ABC-099",
        agent="reviewer",
        kind=OverrideKind.PERSONA,
        value="skeptic",
        channel="web",
        set_at=at(-60),
    ).run(conn)
