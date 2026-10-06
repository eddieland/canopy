"""Prompt files and their overrides: the overseer's prompt (DESIGN §6) and worker prompts (DESIGN §8).

A prompt named `overseer.md` is read from `paths.prompt_overrides` if a file of that name is there, otherwise from the
prompts canopy ships. Worker prompts name their inputs as `{{NAME}}` placeholders.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
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


def render_worker(config: Config, kind: str, values: Mapping[str, str]) -> str:
    """Return the worker prompt for `kind` with every `{{NAME}}` replaced from `values`.

    Replacement is one pass, so a value that itself contains `{{NAME}}` is left as it is. A placeholder with no value
    is an error: an override with a typo must not reach a worker half rendered. So is a prompt that lacks one of
    `REQUIRED_WORKER`.
    """
    path = prompt_path(config, WORKER[kind])
    text = path.read_text(encoding="utf-8")

    def replace(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in values:
            raise PromptError(f"{path}: unknown placeholder {{{{{name}}}}}")
        return values[name]

    rendered = _PLACEHOLDER_RE.sub(replace, text)
    used = set(_PLACEHOLDER_RE.findall(text))
    missing = [f"{{{{{name}}}}}" for name in REQUIRED_WORKER if name not in used]
    if missing:
        raise PromptError(f"{path}: missing required placeholder {', '.join(missing)}")
    return rendered
