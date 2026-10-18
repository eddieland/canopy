"""What `canopy init` writes for every workspace: its private config, and the pieces `setup.workspace` builds on.

The private config is written if missing and never overwritten; the user config is never written (DESIGN §12). Nothing
else is installed: agent runs load canopy's definitions and skills from a directory canopy owns (`definitions.py`).
canopy writes nothing into a code repository (D016).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tomllib
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from pathlib import Path

from canopy.core import config, hostgit
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

# The wrapper canopy installs beside itself, and the prefix it gives a worker run's commands (DESIGN §24).
SANDBOX_WRAPPER = "canopy-sandbox"
SANDBOX_PREFIX = f"{SANDBOX_WRAPPER} worker --read {config.DEFINITIONS_DIR} --"
SANDBOX_SUGGESTION = """\
Optional: run workers in a sandbox, so a steered worker cannot read your secrets or change canopy's config. Run
`canopy sandbox setup` (https://github.com/eddieland/canopy/blob/main/docs/SANDBOX.md), then set this in
{user_file}, which prefixes worker_cmd, private_worker_cmd, split_cmd, and plan_cmd:
  [runtime]
  {line}
"""
# What `canopy sandbox setup` prints instead, having just done that.
SANDBOX_NEXT = """\
Then set this in {user_file}, which prefixes worker_cmd, private_worker_cmd, split_cmd, and plan_cmd
(https://github.com/eddieland/canopy/blob/main/docs/SANDBOX.md, step 5):
  [runtime]
  {line}
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


def ssh_push_urls(runner: procs.Runner, clone: Path) -> list[str]:
    """Return `origin`'s push URLs in `clone` that go over SSH, after `insteadOf` rewrites. Empty if it has none."""
    try:
        result = runner.run(hostgit.argv("remote", "get-url", "--push", "--all", "origin"), cwd=clone, timeout=30)
    except procs.ProcError:
        return []
    if not result.ok:
        return []
    return [url for url in result.stdout.split() if is_ssh_url(url)]


def sandbox_suggestion(runtime: config.Runtime, user_file: Path, *, text: str = SANDBOX_SUGGESTION) -> str:
    """Return how to sandbox workers: `runtime.worker_cmd_prefix` behind `canopy-sandbox`'s, as a line of `user_file`.

    `text` says it, with `{user_file}` and `{line}` in it: `canopy init`'s, by default.

    Printed, never written: the sandbox is opt-in, and needs `canopy sandbox setup` run first (DESIGN §24).

    Returns:
        The text to print, or "" when `worker_cmd` already runs through `canopy-sandbox`, by its prefix or its own.
    """
    if Path(config.command_words(runtime.worker_template(runtime.worker_cmd))[0]).name == SANDBOX_WRAPPER:
        return ""
    value = " ".join(part for part in (SANDBOX_PREFIX, runtime.worker_cmd_prefix) if part)
    line = f"worker_cmd_prefix = '{value}'"
    # A prefix TOML reads from a basic string can hold what a literal one cannot: a quote, a control character.
    with contextlib.suppress(tomllib.TOMLDecodeError):
        if tomllib.loads(line)["worker_cmd_prefix"] == value:
            return text.format(user_file=user_file, line=line)
    return text.format(user_file=user_file, line=f"worker_cmd_prefix = {json.dumps(value, ensure_ascii=False)}")


@dataclass
class Report:
    """What init wrote, updated, and left alone, the label a new private file got, and old agent definitions."""

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


def keys_set(path: Path) -> set[str]:
    """The `section.key` names a TOML config file sets, to leave them out of a new private file.

    Returns:
        Each key of each table, as `section.key`; empty when the file is missing or is not valid TOML.
    """
    try:
        with path.open("rb") as f:
            doc = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return set()
    return {f"{section}.{key}" for section, table in doc.items() if isinstance(table, dict) for key in table}


def private_config_text(label: str | None, user_keys: AbstractSet[str]) -> str:
    """Return the text of a new private config file.

    It sets queue label `label`, unless None, and empty `trust.authorized_repliers` and `trust.trusted_reviewers` to
    fill in, each unless `user_keys`, what the user file sets, holds it.

    Returns:
        The file's text: comments, and the tables of whichever of those keys it sets.
    """
    text = f"""\
# canopy's private config for this workspace: yours alone, never committed. It overrides canopy-workspace.toml and
# your user config ({config.user_config_path()}) key by key. Keep here what belongs to this workspace: its labels,
# who may steer its workers, its chores, its pacing and capacity, its web UI's port. Keep in the user config what serves
# every workspace: the runtime templates, the comment marks, notification sinks. Only what is yours to decide is here;
# every other key keeps its default, and gets new ones as canopy changes. A relative paths.* value names a file in
# this directory. Every key, with its default: https://github.com/eddieland/canopy/blob/main/examples/config.toml
"""
    if label is not None:
        text += f"""
[tracker]
# Your queue. A ticket is yours if it carries any of these labels. Never share a label with another operator:
# both loops would work the same tickets.
labels = [{json.dumps(label)}]
"""
    trust = ""
    if "trust.authorized_repliers" not in user_keys:
        trust += """\
# Tracker account ids whose ticket comments may resume your blocked work: Jira accountId, GitHub login.
# Empty means nobody can, you included: add your own.
authorized_repliers = []
"""
    if "trust.trusted_reviewers" not in user_keys:
        trust += """\
# GitHub logins whose PR review comments a worker may address unasked; "canopy:review" for canopy's own reviewer.
# Empty means everyone's wait on the attention list for your go-ahead: `canopy reply KEY 'what to do about them'`.
trusted_reviewers = []
"""
    return text + (f"\n[trust]\n{trust}" if trust else "")


def write_private_if_missing(path: Path, text: str, report: Report) -> None:
    """Write `text` to `path`, readable only by the operator, unless something is there; record which in `report`.

    A symlink at `path` is something there: it is kept, never followed.
    """
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        report.kept.append(path)
        return
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    report.written.append(path)


def write_if_missing(path: Path, text: str, report: Report) -> None:
    """Write `text` to `path` unless it exists, and record which in `report`."""
    if path.exists():
        report.kept.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    report.written.append(path)
