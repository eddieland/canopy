"""Prompt files and their overrides: the overseer's prompt (DESIGN §6) and worker prompts (DESIGN §8).

A prompt named `overseer.md` is read from `paths.prompt_overrides` if a file of that name is there, otherwise from the
prompts canopy ships. Worker prompts name their inputs as `{{NAME}}` placeholders.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

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
# The reviewer's prompt (DESIGN §21). An override must still name the commit, the checkout, and the run, which the
# reviewer's comment marker carries, so the loop can tell its reviews from anything else.
REVIEWER = "reviewer.md"
REQUIRED_REVIEWER = ("PR_URL", "SHA", "CHECKOUT", "RUN_ID")


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


def render_worker(config: Config, kind: str, values: Mapping[str, str], *, required: Sequence[str] = ()) -> str:
    """Return the worker prompt for `kind` with every `{{NAME}}` replaced from `values`.

    Replacement is one pass, so a value that itself contains `{{NAME}}` is left as it is. A placeholder with no value
    is an error: an override with a typo must not reach a worker half rendered. So is a prompt that lacks one of
    `REQUIRED_WORKER`, or of `required`.
    """
    return render(config, WORKER[kind], values, required=(*REQUIRED_WORKER, *required))


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
