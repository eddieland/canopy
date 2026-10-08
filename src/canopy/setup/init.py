"""`canopy init`: set up canopy for a repository and an operator.

Writes the user config and repository config if missing, and prints the branch protection canopy relies on (DESIGN §12,
TRUST_MODEL §7). Warns when `origin` pushes over SSH (D038), and when the repository still has copies of canopy's agent
definitions from an earlier canopy (D040, D044).

Neither config file is ever overwritten. Nothing else is installed: agent runs load canopy's definitions and skills from
a directory canopy owns (`definitions.py`).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from canopy.core import definitions
from canopy.core.config import REPO_FILE_NAME
from canopy.infra import procs

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

SSH_REMOTE_WARNING = """\
Warning: origin pushes over SSH ({urls}).
  canopy strongly recommends HTTPS remotes with a credential helper (D038). Worker sandboxing is expected to block
  the SSH agent socket, so a sandboxed worker could not push. This is a recommendation; nothing is refused. To switch:
    git remote set-url origin https://<host>/<owner>/<repo>.git
  or keep the SSH URL and rewrite it for pushes: git config url.https://<host>/.pushInsteadOf git@<host>:
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


def ssh_push_urls(runner: procs.Runner, repo_root: Path) -> list[str]:
    """Return `origin`'s push URLs that go over SSH, after `insteadOf` rewrites. Empty if there is no `origin`."""
    try:
        result = runner.run(["git", "remote", "get-url", "--push", "--all", "origin"], cwd=repo_root, timeout=30)
    except procs.ProcError:
        return []
    if not result.ok:
        return []
    return [url for url in result.stdout.split() if is_ssh_url(url)]


@dataclass
class Report:
    """What `run` wrote, updated, and left alone, the label it chose for a new user file, and old agent definitions."""

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
# canopy user config: personal, never committed. Overrides the repository's canopy.toml key by key.
# Keys marked user-only in DESIGN.md §12 may be set only here. Every key, with comments:
# https://github.com/eddieland/canopy/blob/main/examples/config.toml

[tracker]
# Your queue. A ticket is yours if it carries any of these labels. Never share a label with another operator:
# both loops would work the same tickets.
labels = [{json.dumps(label)}]

[capacity]
max_workers = 2

[runtime]
# {{definitions_dir}} is the directory canopy's agent definitions and skills are in (D040). Keep it.
overseer_cmd = 'env OPENCODE_CONFIG_DIR={{definitions_dir}} opencode run --agent canopy-overseer {{prompt}}'
worker_cmd   = 'env OPENCODE_CONFIG_DIR={{definitions_dir}} opencode run --agent canopy-worker --format json {{prompt}}'
overseer_timeout_minutes = 15
worker_timeout_minutes = 45

[loop]
# `canopy loop` waits this long after each tick ends. Every tick runs the overseer, so this sets its spend.
interval_minutes = 15

[trust]
# Tracker account ids whose ticket comments may resume your blocked work: Jira accountId, GitHub login.
# Empty means nobody can.
authorized_repliers = []
# Every comment a worker posts starts with the prefix and ends with the suffix, each if set; set at least one.
# A comment that carries every mark set is never feedback or an instruction.
comment_prefix = "CANOPY:"
comment_suffix = ""
"""


def repo_config_text(provider: str) -> str:
    """Return the text of a new `canopy.toml` for tracker `provider`."""
    query = EXAMPLE_QUERIES.get(provider, "describe which tickets to look at, in plain language")
    return f"""\
# canopy.toml: committed at the repository root, shared by everyone who runs canopy on it.
# Shared keys only; personal settings live in the user config (DESIGN.md §12).

[tracker]
provider = {json.dumps(provider)}
# Added by a worker that needs an answer, removed when it resumes. Any label your tracker accepts; it must
# already exist, since canopy does not create labels.
needs_human_label = "needs-human"
# How to find candidate tickets: the tracker's own search syntax, or plain language. Edit this.
# Finding is not authorizing: each operator's own labels are checked on every ticket.
query = {json.dumps(query)}

[trust]
branch_prefix = "agent/"
pr_label = "agent"
"""


def write_if_missing(path: Path, text: str, report: Report) -> None:
    """Write `text` to `path` unless it exists, and record which in `report`."""
    if path.exists():
        report.kept.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    report.written.append(path)


def run(repo_root: Path, user_file: Path, provider: str | None) -> Report:
    """Do the init. `provider` is needed only when the repository has no canopy.toml yet."""
    report = Report()
    if user_file.exists():
        report.kept.append(user_file)
    else:
        report.label = default_label()
        write_if_missing(user_file, user_config_text(report.label), report)

    repo_file = repo_root / REPO_FILE_NAME
    if repo_file.exists():
        report.kept.append(repo_file)
    else:
        if provider is None:
            raise ValueError("the repository has no canopy.toml; a tracker provider is needed to write one")
        write_if_missing(repo_file, repo_config_text(provider), report)

    report.shadowing = definitions.shadowing(repo_root)
    return report
