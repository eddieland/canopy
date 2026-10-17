"""Agent memory (DESIGN §28): ticket notes a ticket's runs write for its later runs, and the operator's lessons.

Each tier is off, recording, or in use (`[memory]`, `config.Memory`). This module says which, in the words every
surface uses, so the operator never takes recorded memory for memory in use, or the reverse.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, assert_never

from canopy.core.vocab import MemoryMode

if TYPE_CHECKING:
    from canopy.core.config import Memory

# What each tier is called wherever memory shows: `memory.ticket_notes` and `memory.proposals`, whose lessons are what
# a run reads.
NOTES_TIER = "ticket notes"
LESSONS_TIER = "lessons"


def mode_words(mode: MemoryMode) -> str:
    """Return a tier's mode in words: `off`, `recording`, or `in use`, never the same label for two modes."""
    match mode:
        case MemoryMode.OFF:
            return "off"
        case MemoryMode.RECORD:
            return "recording"
        case MemoryMode.USE:
            return "in use"
        case _:
            assert_never(mode)


def tiers(memory: Memory) -> str:
    """Return each tier's mode in words, as the readout's hover and `canopy status` say it.

    Returns:
        `ticket notes: recording, lessons: off`, and so on.
    """
    return f"{NOTES_TIER}: {mode_words(memory.ticket_notes)}, {LESSONS_TIER}: {mode_words(memory.proposals)}"


def readout(memory: Memory) -> str | None:
    """Return the web UI's header readout and `canopy status`'s line: whether any memory is read yet.

    Returns:
        `memory: in use` once a tier is at `use`, `memory: recording` while a tier records and none is used, and None
        with both off, when memory shows nowhere.
    """
    if memory.in_use:
        return "memory: in use"
    if memory.on:
        return "memory: recording"
    return None
