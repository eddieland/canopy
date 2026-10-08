"""Prompt files and their overrides: the overseer's prompt (DESIGN §6) and worker prompts (DESIGN §8).

A prompt named `overseer.md` is read from `paths.prompt_overrides` if a file of that name is there, otherwise from the
prompts canopy ships. Worker prompts name their inputs as `{{NAME}}` placeholders.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core.config import CANOPY_REVIEWER
from canopy.infra import resources

if TYPE_CHECKING:
    from canopy.core.config import Config

OVERSEER = "overseer.md"
WORKER = {
    "implement": "worker-implement.md",
    "fix-ci": "worker-fix-ci.md",
    "resume": "worker-resume.md",
    "split": "worker-split.md",
}
# A private ticket's worker prompts (DESIGN §22): no label check, since the harness checked the start record, and
# nothing written to the ticket. Each must carry the conversation, the only way the worker hears the operator's replies;
# an override without it would run without them.
WORKER_PRIVATE = {
    "implement": "worker-implement-private.md",
    "fix-ci": "worker-fix-ci-private.md",
    "resume": "worker-resume-private.md",
}
REQUIRED_PRIVATE = ("CONVERSATION",)
_PLACEHOLDER_RE = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")
# Placeholders every worker prompt must use. `LABELS` carries the worker's own authorization check (D051); an override
# written before it existed would silently drop that check, so it fails to render instead.
REQUIRED_WORKER = ("LABELS",)
# Placeholders a joint run's prompt must also use: its worker learns its repositories and the result's `prs` from them
# (DESIGN §18). A prompt without them still serves a run in one repository.
REQUIRED_JOINT = ("REPOSITORIES", "PRS")
# Placeholders a split's prompt must also use: its repositories, and the comment that asked for the split, which the
# splitter reads to check who asked (D061). An override without it would split on the overseer's word alone.
REQUIRED_SPLIT = ("REPOSITORIES", "REQUEST")
# The kinds whose workers open PRs. With `runtime.pr_skill` set, their prompts must say how, through `{{OPEN_PR}}`: an
# override that still names the GitHub MCP would open the PRs the operator set the skill to avoid (D078).
OPENS_PRS = ("implement", "resume")
REQUIRED_PR_SKILL = ("OPEN_PR",)
# The reviewer's prompt (DESIGN §21). An override must still name the commit, the checkout, and the run, which the
# reviewer's comment marker carries, so the loop can tell its reviews from anything else.
REVIEWER = "reviewer.md"
REQUIRED_REVIEWER = ("PR_URL", "SHA", "CHECKOUT", "RUN_ID")


def worker_comment(prefix: str, suffix: str) -> str:
    """Return how a worker's comment is recognized (D069), to follow "a comment that": it carries every mark set.

    Marks inside a quote do not count, so a human's reply that quotes a worker's comment stays the human's.
    """
    marks = [f"starts with `{prefix}`"] if prefix else []
    if suffix:
        marks.append(f"ends with `{suffix}`")
    return f"{' and '.join(marks)} outside any quote"


def trusted_reviewers(reviewers: Sequence[str]) -> str:
    """Return the worker's list of trusted reviewers (DESIGN §7, D089), naming canopy's own reviewer in words."""
    names = [
        "canopy's own reviewer (a comment canopy's review run posted)" if r == CANOPY_REVIEWER else f"`{r}`"
        for r in reviewers
    ]
    return ", ".join(names) if names else "none (every reviewer's feedback needs the operator's go-ahead)"


def mark_comments(prefix: str, suffix: str) -> str:
    """Return the instruction that has a worker mark each comment it posts (D069)."""
    marks = [f"start it with `{prefix}` and a space"] if prefix else []
    if suffix:
        marks.append(f"end it with `{suffix}`")
    return f"In every comment and reply you post, on the ticket or a PR, {', and '.join(marks)}, without the backticks."


def open_pr(skill: str) -> str:
    """Return how a worker opens a PR: through the GitHub MCP, or with the operator's skill and nothing else (D078).

    A missing skill is a failed run, not a fallback to the MCP: the operator set the skill because the MCP's PRs do not
    work for them.
    """
    if not skill:
        return "Open each PR through the GitHub MCP."
    return (
        f"Open each PR by following the skill `{skill}`, and in no other way: load it before you open one. If no skill "
        f"named `{skill}` is available, open no PR and report `failed` with a summary that starts `no PR skill:`."
    )


class PromptError(Exception):
    """A prompt file cannot be rendered."""


def prompt_path(config: Config, name: str) -> Path:
    """Return the prompt file `name`, preferring the operator's override."""
    override = config.paths.prompt_overrides / name
    if override.is_file():
        return override
    return resources.prompts_dir() / name


def render_overseer(config: Config, block: str) -> str:
    """Return the overseer prompt followed by the state block."""
    body = prompt_path(config, OVERSEER).read_text(encoding="utf-8").rstrip("\n")
    return f"{body}\n\n{block}"


def render_worker(
    config: Config, kind: str, values: Mapping[str, str], *, required: Sequence[str] = (), private: bool = False
) -> str:
    """Return the worker prompt for `kind` with every `{{NAME}}` replaced from `values`.

    Replacement is one pass, so a value that itself contains `{{NAME}}` is left as it is. A placeholder with no value
    is an error: an override with a typo must not reach a worker half rendered. So is a prompt that lacks one of
    `REQUIRED_WORKER`, or of `required`, and, with `runtime.pr_skill` set, a prompt for a kind that opens PRs that lacks
    `REQUIRED_PR_SKILL`. A `private` prompt is a private ticket's, which must carry `REQUIRED_PRIVATE` in place of
    `REQUIRED_WORKER`: it checks no label.
    """
    pr_skill = REQUIRED_PR_SKILL if config.runtime.pr_skill and kind in OPENS_PRS else ()
    if private:
        return render(config, WORKER_PRIVATE[kind], values, required=(*REQUIRED_PRIVATE, *pr_skill, *required))
    return render(config, WORKER[kind], values, required=(*REQUIRED_WORKER, *pr_skill, *required))


def render(config: Config, name: str, values: Mapping[str, str], *, required: Sequence[str] = ()) -> str:
    """Return prompt file `name` with every `{{NAME}}` replaced from `values`, in one pass.

    A placeholder with no value is an error, and so is a prompt that lacks one of `required`.
    """
    path = prompt_path(config, name)
    text = path.read_text(encoding="utf-8")

    def replace(m: re.Match[str]) -> str:
        placeholder = m.group(1)
        if placeholder not in values:
            raise PromptError(f"{path}: unknown placeholder {{{{{placeholder}}}}}")
        return values[placeholder]

    rendered = _PLACEHOLDER_RE.sub(replace, text)
    used = set(_PLACEHOLDER_RE.findall(text))
    missing = [f"{{{{{n}}}}}" for n in required if n not in used]
    if missing:
        raise PromptError(f"{path}: missing required placeholder {', '.join(missing)}")
    return rendered
