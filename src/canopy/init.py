"""`canopy init`: set up canopy for a repository and an operator.

Writes the user config and repository config if missing, installs agent definitions and the tracker skill, and prints
the branch protection canopy relies on (DESIGN §12, TRUST_MODEL §7). Warns when `origin` pushes over SSH (D038).

Neither config file is ever overwritten. Agent definitions and skills are canopy's own files and are refreshed.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from canopy import procs, resources
from canopy.config import REPO_FILE_NAME

AGENT_DIR = Path(".opencode/agent")
# OpenCode reads skills from .opencode/skill/<name>/SKILL.md (and .opencode/skills/).
SKILL_DIR = Path(".opencode/skill")
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
    """What `run` wrote, what it left alone, and the label it chose for a new user file."""

    written: list[Path] = field(default_factory=list)
    kept: list[Path] = field(default_factory=list)
    label: str | None = None


def default_label() -> str:
    """Return the default queue label, `agent-ready-<$USER>`, reduced to safe characters."""
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or "me"
    # Labels end up in tracker queries; keep them to characters every tracker accepts.
    return "agent-ready-" + (re.sub(r"[^A-Za-z0-9_-]+", "-", user).strip("-").lower() or "me")


def user_config_text(label: str) -> str:
    """Return the text of a new user config file with queue label `label`."""
    return f"""\
# canopy user config: personal, never committed. Overrides the repository's canopy.toml key by key.
# Keys marked user-only in DESIGN.md §12 may be set only here. See examples/config.toml for every key.

[tracker]
# Your queue. A ticket is yours if it carries any of these labels. Never share a label with another operator:
# both loops would work the same tickets.
labels = [{json.dumps(label)}]

[capacity]
max_workers = 2

[runtime]
overseer_cmd = 'opencode run --agent canopy-overseer {{prompt}}'
worker_cmd   = 'opencode run --agent canopy-worker {{prompt}}'
overseer_timeout_minutes = 15
worker_timeout_minutes = 45

[trust]
# Tracker account ids whose ticket comments may resume your blocked work: Jira accountId, GitHub login.
# Empty means nobody can.
authorized_repliers = []
"""


def repo_config_text(provider: str) -> str:
    """Return the text of a new `canopy.toml` for tracker `provider`."""
    query = EXAMPLE_QUERIES.get(provider, "describe which tickets to look at, in plain language")
    return f"""\
# canopy.toml: committed at the repository root, shared by everyone who runs canopy on it.
# Shared keys only; personal settings live in the user config (DESIGN.md §12).

[tracker]
provider = {json.dumps(provider)}
needs_human_label = "needs-human"
# How to find candidate tickets: the tracker's own search syntax, or plain language. Edit this.
# Finding is not authorizing: each operator's own labels are checked on every ticket.
query = {json.dumps(query)}

[trust]
branch_prefix = "agent/"
pr_label = "agent"
"""


def _write_if_missing(path: Path, text: str, report: Report) -> None:
    if path.exists():
        report.kept.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    report.written.append(path)


def _install(src: Path, dest: Path, report: Report) -> None:
    text = src.read_text(encoding="utf-8")
    if dest.exists() and dest.read_text(encoding="utf-8") == text:
        report.kept.append(dest)
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    report.written.append(dest)


def run(repo_root: Path, user_file: Path, provider: str | None) -> Report:
    """Do the init. `provider` is needed only when the repository has no canopy.toml yet."""
    report = Report()
    if user_file.exists():
        report.kept.append(user_file)
    else:
        report.label = default_label()
        _write_if_missing(user_file, user_config_text(report.label), report)

    repo_file = repo_root / REPO_FILE_NAME
    if repo_file.exists():
        # The committed file decides the provider; `provider` only seeds a new one.
        report.kept.append(repo_file)
        provider = _provider_from(repo_file)
    else:
        if provider is None:
            raise ValueError("the repository has no canopy.toml; a tracker provider is needed to write one")
        _write_if_missing(repo_file, repo_config_text(provider), report)

    for src in sorted(resources.agents_dir().glob("*.md")):
        _install(src, repo_root / AGENT_DIR / src.name, report)

    if provider is not None and valid_provider(provider):
        skill = resources.skills_dir() / f"tracker-{provider}" / "SKILL.md"
        if skill.is_file():
            _install(skill, repo_root / SKILL_DIR / f"tracker-{provider}" / "SKILL.md", report)
    return report


def _provider_from(repo_file: Path) -> str | None:
    try:
        with repo_file.open("rb") as f:
            tracker = tomllib.load(f).get("tracker", {})
    except (OSError, tomllib.TOMLDecodeError):
        return None
    provider = tracker.get("provider") if isinstance(tracker, dict) else None
    return provider if isinstance(provider, str) else None
