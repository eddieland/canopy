"""What `canopy stop --now` did to a task's or an epic's running run (DESIGN §22, §36, §43), as it is told back.

The stop records that it was asked before it kills anything (`db.ask_stop`), so a run whose stop did not live to close
it is closed `stopped` by reconcile, not `crashed`. A slot the run held that could not be tidied or returned stays
leased: it is said so, never reported returned.
"""

from __future__ import annotations

from enum import Enum


class Ending(Enum):
    """How a stop that ends a running run now ended it."""

    #: The run had already ended: nothing changed.
    GONE = "gone"
    #: The run was closed `stopped`, and every slot it held returned to its pool.
    ENDED = "ended"
    #: The run was closed `stopped`, but a slot it held could not be tidied or returned: it is left leased, for the next
    #: tick's reconcile or, one that could not be tidied, for the operator, and the log says which.
    KEPT = "kept"


#: What a stop says of a slot it could not return, after `but its slot was not returned;`, in the CLI and the web UI.
KEPT_NOTE = "the next tick returns it, or one canopy could not tidy stays leased for you: canopy.log says which"
