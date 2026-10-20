"""Agent memory (DESIGN §28, ROADMAP M50): its config, its modes in words, and canopy with every tier off."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from canopy.cli.main import main
from canopy.core import memory
from canopy.core.config import ConfigError, load
from canopy.core.vocab import MemoryMode
from tests.canopy.helpers import with_memory

if TYPE_CHECKING:
    from tests.conftest import CanopyEnv


def test_memory_is_off_unless_the_operator_turns_a_tier_on(canopy_env: CanopyEnv) -> None:
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert (cfg.memory.ticket_notes, cfg.memory.proposals) == (MemoryMode.OFF, MemoryMode.OFF)
    assert not cfg.memory.on
    assert memory.readout(cfg.memory) is None


@pytest.mark.parametrize("tier", ["ticket_notes", "review_notes"])
def test_the_workspace_file_cannot_turn_memory_on(canopy_env: CanopyEnv, tier: str) -> None:
    canopy_env.append_shared(f'\n[memory]\n{tier} = "use"\n')
    with pytest.raises(ConfigError, match=rf"memory\.{tier} is private and cannot be set in the workspace file"):
        load(canopy_env.root, canopy_env.user_file)


def test_a_mode_the_vocabulary_does_not_hold_is_a_config_error(canopy_env: CanopyEnv) -> None:
    with_memory(canopy_env, ticket_notes="on")
    with pytest.raises(ConfigError, match=r"memory\.ticket_notes"):
        load(canopy_env.root, canopy_env.user_file)


@pytest.mark.parametrize(
    ("ticket_notes", "proposals", "review_notes", "readout", "tiers"),
    [
        ("record", "off", "off", "memory: recording", "ticket notes: recording, lessons: off"),
        ("off", "record", "off", "memory: recording", "ticket notes: off, lessons: recording"),
        ("use", "record", "off", "memory: in use", "ticket notes: in use, lessons: recording"),
        ("off", "use", "off", "memory: in use", "ticket notes: off, lessons: in use"),
        # Review notes are named only while they are on, so every readout before them reads as it did.
        ("off", "off", "record", "memory: recording", "ticket notes: off, lessons: off, review notes: recording"),
        ("record", "off", "use", "memory: in use", "ticket notes: recording, lessons: off, review notes: in use"),
    ],
)
def test_each_mode_has_words_of_its_own(
    canopy_env: CanopyEnv, ticket_notes: str, proposals: str, review_notes: str, readout: str, tiers: str
) -> None:
    with_memory(canopy_env, ticket_notes, proposals, review_notes)
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert memory.readout(cfg.memory) == readout
    assert memory.tiers(cfg.memory) == tiers


def test_with_memory_off_canopy_memory_says_so_and_status_has_no_memory_line(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["memory", "list"]) == 0
    assert capsys.readouterr().out.startswith(
        "Memory is off: memory.ticket_notes, memory.proposals, and memory.review_notes are all off"
    )
    assert main(["status"]) == 0
    assert "memory:" not in capsys.readouterr().out


def test_status_says_which_tier_records(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    with_memory(canopy_env, ticket_notes="record")
    assert main(["status"]) == 0
    assert "memory: recording (ticket notes: recording, lessons: off)\n" in capsys.readouterr().out
