"""Agent memory's placeholders in the worker prompts (DESIGN §28), against snapshots recorded before memory existed.

With `[memory]` unset every tier is off, and each prompt must be the same bytes it was before the milestone: the
snapshots in `__snapshots__/test_memory_prompts/` were recorded from the prompts canopy shipped then, and are never
recorded again while memory is off.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from syrupy.extensions.single_file import SingleFileSnapshotExtension, WriteMode

from canopy.core import prompts
from canopy.core.config import load
from canopy.core.vocab import RunKind
from tests.canopy.helpers import PROMPT_VALUES

if TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion

    from tests.conftest import CanopyEnv

# Every prompt a worker run can be rendered from: each kind's public prompt, and the private variants.
PROMPTS = [
    *((str(kind), False) for kind in prompts.WORKER),
    *((str(kind), True) for kind in prompts.WORKER_PRIVATE),
]
VALUES = {
    **PROMPT_VALUES,
    "AUTHORIZATION": prompts.plan_authorization("PROJ-1", ["agent-ready-alice"], private=False),
    "PLAN_FILE": ".canopy-plan.md",
    "PLAN_OUT": ".canopy-new-plan.md",
    "MAX_PLAN_CHARS": "100,000",
    "CONVERSATION": "No messages yet.",
}


class MarkdownSnapshot(SingleFileSnapshotExtension):
    """A snapshot as a Markdown file of its own, as the worker reads its prompt."""

    file_extension = "md"
    _write_mode = WriteMode.TEXT


@pytest.fixture
def prompt(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """The test's prompt snapshot."""
    return snapshot.use_extension(MarkdownSnapshot)


@pytest.mark.parametrize(("kind", "private"), PROMPTS, ids=[f"{k}{'-private' if p else ''}" for k, p in PROMPTS])
def test_with_memory_off_every_worker_prompt_is_as_it_was(
    canopy_env: CanopyEnv, prompt: SnapshotAssertion, kind: str, *, private: bool
) -> None:
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert prompts.render_worker(cfg, kind, VALUES, private=private and kind != RunKind.PLAN) == prompt
