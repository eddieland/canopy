"""What `canopy init` writes for every workspace: the user config, and the pieces `setup.workspace` builds on.

The user config is written if missing and never overwritten. Nothing else is installed: agent runs load canopy's
definitions and skills from a directory canopy owns (`definitions.py`). canopy writes nothing into a code repository
(D016).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# A provider name becomes a directory name; keep it to one plain path component.
PROVIDER_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")


def valid_provider(provider: str) -> bool:
    """Return whether `provider` is a plain name that is safe as one path component."""
    return PROVIDER_RE.fullmatch(provider) is not None


EXAMPLE_QUERIES = {
    "jira": "project = PROJ AND statusCategory != Done ORDER BY priority DESC, created ASC",
    "github": "repo:OWNER/NAME is:issue is:open",
}

BRANCH_PROTECTION = """\
Branch protection canopy relies on (TRUST_MODEL §7). Configure it on the repository host:
  - Protect the default branch and every release branch: no direct pushes, no force pushes.
  - Require pull request reviews before merging, and do not let authors approve their own PRs.
  - Require status checks to pass before merging.
  - Workers push only to branches under {prefix}; nothing else should be pushable by the loop.
"""

# Transports git runs over ssh. Anything else with `://` (https, git, file) is not SSH.
_SSH_SCHEMES = ("ssh://", "git+ssh://", "ssh+git://")


def is_ssh_url(url: str) -> bool:
    """Return whether git would reach `url` over SSH.

    That is an `ssh://` URL, or the scp-like `[user@]host:path` form: no `://`, and a colon before the first slash.
    """
    url = url.strip()
    if url.lower().startswith(_SSH_SCHEMES):
        return True
    if "://" in url:
        return False
    colon = url.find(":")
    slash = url.find("/")
    return colon > 0 and (slash == -1 or colon < slash)


@dataclass
class Report:
    """What init wrote, updated, and left alone, the label it chose for a new user file, and old agent definitions."""

    written: list[Path] = field(default_factory=list)
    kept: list[Path] = field(default_factory=list)
    updated: list[Path] = field(default_factory=list)
    label: str | None = None
    shadowing: list[Path] = field(default_factory=list)


def default_label() -> str:
    """Return the default queue label, `agent-ready-<$USER>`, reduced to safe characters."""
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or "me"
    # Labels end up in tracker queries; keep them to characters every tracker accepts.
    return "agent-ready-" + (re.sub(r"[^A-Za-z0-9_-]+", "-", user).strip("-").lower() or "me")


def user_config_text(label: str) -> str:
    """Return the text of a new user config file with queue label `label`."""
    return f"""\
# canopy user config: personal, never committed. Overrides each workspace's canopy-workspace.toml key by key.
# Only what is yours to decide is here; every other key keeps its default, and gets new ones as canopy changes. Keys
# marked user-only in DESIGN.md §12 may be set only here. Every key, with its default:
# https://github.com/eddieland/canopy/blob/main/examples/config.toml

[tracker]
# Your queue. A ticket is yours if it carries any of these labels. Never share a label with another operator:
# both loops would work the same tickets.
labels = [{json.dumps(label)}]

[trust]
# Tracker account ids whose ticket comments may resume your blocked work: Jira accountId, GitHub login.
# Empty means nobody can, you included: add your own.
authorized_repliers = []
# GitHub logins whose PR review comments a worker may address unasked; "canopy:review" for canopy's own reviewer.
# Empty means everyone's wait on the attention list for your go-ahead: `canopy reply KEY 'what to do about them'`.
trusted_reviewers = []
"""


def write_if_missing(path: Path, text: str, report: Report) -> None:
    """Write `text` to `path` unless it exists, and record which in `report`."""
    if path.exists():
        report.kept.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    report.written.append(path)
