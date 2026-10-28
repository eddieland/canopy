"""How a worker's prompt says its comments reach GitHub (DESIGN §29): posted under `post`, drafted under `approve`.

Under `post` each prompt is the same bytes as before the setting existed, which `test_memory_prompts.py`'s snapshots,
recorded before it, hold. The prompts under `approve` are held here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from canopy.core import prompts, replies
from canopy.core.config import load
from canopy.core.vocab import ReplyMode, RunKind
from tests.canopy.helpers import PRIVATE_PROMPT_VALUES, PROMPT_VALUES, present

if TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion

    from tests.conftest import CanopyEnv

TRACKER_POSTS = '\n[connect.sources.issues]\nkind = "tracker"\npost_cmd = "canopy-post-github"\n'
DRAFTING = [
    (RunKind.IMPLEMENT, False, False),
    (RunKind.IMPLEMENT, False, True),
    (RunKind.IMPLEMENT, True, False),
    (RunKind.RESUME, False, False),
    (RunKind.RESUME, False, True),
    (RunKind.RESUME, True, False),
]


def approving(env: CanopyEnv, *, tracker_posts: bool = False) -> None:
    env.write_private('[trust]\nreview_replies = "approve"\n' + (TRACKER_POSTS if tracker_posts else ""))


@pytest.mark.parametrize(
    ("kind", "private", "tracker_posts"),
    DRAFTING,
    ids=[f"{k}{'-private' if p else ''}{'-ticket-drafts' if t else ''}" for k, p, t in DRAFTING],
)
def test_under_approve_a_prompt_asks_for_drafts(
    canopy_env: CanopyEnv,
    markdown_snapshot: SnapshotAssertion,
    kind: RunKind,
    *,
    private: bool,
    tracker_posts: bool,
) -> None:
    approving(canopy_env, tracker_posts=tracker_posts)
    cfg = load(canopy_env.root, canopy_env.user_file)
    rendered = present(replies.render(cfg, kind, private=private))
    assert rendered.mode is ReplyMode.APPROVE
    # A private ticket's worker writes nothing to the ticket, so it is never asked for a ticket's draft.
    assert rendered.ticket_drafts is (tracker_posts and not private)
    base = PRIVATE_PROMPT_VALUES if private else PROMPT_VALUES
    values = {**base, "CONVERSATION": "No messages yet.", **rendered.values}
    text = prompts.render_worker(cfg, kind, values, private=private, required=rendered.required)
    assert text == markdown_snapshot


def test_under_post_nothing_is_required_and_drafts_render_empty(canopy_env: CanopyEnv) -> None:
    canopy_env.write_private('[trust]\nreview_replies = "post"\n')
    cfg = load(canopy_env.root, canopy_env.user_file)
    rendered = present(replies.render(cfg, RunKind.RESUME, private=False))
    assert (rendered.mode, rendered.ticket_drafts, rendered.required) == (ReplyMode.POST, False, ())
    assert rendered.values[replies.DRAFTS] == ""


@pytest.mark.parametrize(
    ("mode", "flaky_comment", "asked"),
    [("approve", True, True), ("approve", False, False), ("post", True, False)],
)
def test_a_flaky_check_is_explained_in_a_draft_only_under_approve_when_asked(
    canopy_env: CanopyEnv,
    mode: str,
    *,
    flaky_comment: bool,
    asked: bool,
) -> None:
    """A comment the worker posted itself would carry the marks, so the estimate is only ever a draft (DESIGN §23)."""
    canopy_env.write_private(f'[trust]\nreview_replies = "{mode}"\nflaky_comment = {str(flaky_comment).lower()}\n')
    cfg = load(canopy_env.root, canopy_env.user_file)
    rendered = present(replies.render(cfg, RunKind.RESUME, private=False))
    values = {**PROMPT_VALUES, "CONVERSATION": "No messages yet.", **rendered.values}
    text = prompts.render_worker(cfg, RunKind.RESUME, values, private=False, required=rendered.required)
    ci_note = rendered.values["CI_NOTE"]
    assert (f"{ci_note}{replies.FLAKY_NOTE}\n" in text) is asked
    assert f"{ci_note}\n" in text or asked


def test_under_approve_a_prompt_must_carry_drafts_but_a_private_implements(canopy_env: CanopyEnv) -> None:
    approving(canopy_env)
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert present(replies.render(cfg, RunKind.RESUME, private=True)).required == ("DRAFTS",)
    assert present(replies.render(cfg, RunKind.IMPLEMENT, private=False)).required == ("DRAFTS",)
    # It posts nothing anywhere, so it has nothing to draft.
    assert present(replies.render(cfg, RunKind.IMPLEMENT, private=True)).required == ()


def test_a_kind_that_comments_nowhere_has_no_part(canopy_env: CanopyEnv) -> None:
    approving(canopy_env)
    assert replies.render(load(canopy_env.root, canopy_env.user_file), RunKind.PLAN, private=False) is None
