"""The directory agent runs load canopy's agent definitions and skills from (DESIGN §13, D040).

canopy snapshots its bundled agents and skills into `<state_dir>/runtime/<digest>/`, named for a digest of their
contents. A snapshot is written to a temporary directory and renamed into place, so a run never sees a partial one.
Command templates name it with `{definitions_dir}`, and the runtime reads it as its config directory.

Some definitions are rendered from config: what canopy decides here, from config, that each agent may do
(`canopy.runtime.agents.Rules`), the runtime package writes in its own format. The digest covers the rendered text, so a
config or override change makes a new snapshot rather than changing one a run may be loading.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import prompts, replies
from canopy.core.config import NO_TEMPERATURE
from canopy.core.vocab import ReplyMode, RunKind
from canopy.infra import logs
from canopy.runtime import agents
from canopy.runtime import definitions as runtime_definitions
from canopy.runtime.agents import DefinitionsError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from canopy.core.config import Config

# Kept importable from here: the features catch `DefinitionsError` as the snapshot's.
__all__ = ["RUNTIME_DIR", "DefinitionsError", "digest", "ensure", "prune", "rules", "sources"]

RUNTIME_DIR = "runtime"
_TMP_PREFIX = ".tmp-"
# A temporary directory this old belongs to a process that died mid-copy; a copy takes well under a second.
_STALE_TMP_SECONDS = 3600


def sources(config: Config | None = None) -> dict[str, bytes]:
    """Return the snapshot's files by relative path.

    They are the bundled agents and skills, with the workers', the reviewer's, and the overseer's definitions rendered
    from `config` when it is given.

    Raises:
        DefinitionsError: The overseer's prompt cannot be rendered, or a shipped definition cannot be rendered.
    """
    found = runtime_definitions.bundled()
    return found if config is None else runtime_definitions.render(found, rules(config))


def rules(config: Config) -> agents.Rules:
    """Return what `config` lets each agent do, for the runtime to write into its definitions.

    Raises:
        DefinitionsError: The overseer's prompt cannot be rendered (`prompts.render_overseer`).
    """
    try:
        prompt = prompts.render_overseer(config)
    except prompts.PromptError as e:
        raise DefinitionsError(str(e)) from e
    runtime = config.runtime
    temperatures = {
        agents.REVIEWER: runtime.review_temperature,
        agents.OVERSEER: runtime.overseer_temperature,
    }
    return agents.Rules(
        tracker_tools=config.tracker.tools(),
        rebase=config.trust.rebase,
        worker_drafts=_drafts(config, private=False),
        private_drafts=_drafts(config, private=True),
        temperatures={agent: None if t == NO_TEMPERATURE else t for agent, t in temperatures.items()},
        overseer_prompt=prompt,
        tracker_provider=config.tracker.provider,
    )


def _drafts(config: Config, *, private: bool) -> agents.Drafts:
    replied = replies.render(config, RunKind.RESUME, private=private)
    approve = replied is not None and replied.mode is ReplyMode.APPROVE
    # A public worker without a ticket's draft posts its ticket comments itself; a private one posts none.
    return agents.Drafts(
        approve=approve,
        ticket_comments=not private and not (replied is not None and replied.ticket_drafts),
    )


def digest(config: Config | None = None) -> str:
    """Return a digest of the snapshot's files: their relative paths and contents."""
    return _digest(sources(config))


def _digest(files: Mapping[str, bytes]) -> str:
    h = hashlib.sha256()
    for rel, data in sorted(files.items()):
        h.update(f"{rel}\0{len(data)}\0".encode())
        h.update(data)
    return h.hexdigest()[:16]


def ensure(state_dir: Path, config: Config | None = None) -> Path:
    """Return the snapshot for the installed canopy and `config`, creating it if missing.

    Safe to call from concurrent processes.

    canopy creates a snapshot readable only by the operator. One that is not was put there by something else, such as a
    checkout of a shared workspace (DESIGN §18), and could loosen canopy's agents, so it is refused, never loaded.

    Raises:
        DefinitionsError: the snapshot's directory exists and is not private to the operator, or the overseer's prompt
            cannot be rendered.
        OSError: the snapshot could not be written, and no other process put one in its place.
    """
    files = sources(config)
    runtime = state_dir / RUNTIME_DIR
    final = runtime / _digest(files)
    if final.is_dir() or final.is_symlink():
        return _checked(final)
    runtime.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=_TMP_PREFIX, dir=runtime))
    try:
        for rel, data in files.items():
            path = tmp / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        os.rename(tmp, final)  # noqa: PTH104  (os.rename, unlike Path.replace, never replaces a non-empty directory)
    except OSError:
        shutil.rmtree(tmp, ignore_errors=True)
        # Another process renamed its copy into place first; theirs has the same contents.
        if final.is_dir():
            return _checked(final)
        raise
    return final


def _checked(snapshot: Path) -> Path:
    if not logs.private_dir(snapshot):
        raise DefinitionsError(
            f"{snapshot} is not a snapshot canopy made: canopy creates it readable only by you, and this one is a "
            "symlink, someone else's, or open to others. Remove it; canopy recreates it.",
        )
    return snapshot


def prune(state_dir: Path, keep: Path) -> list[Path]:
    """Remove snapshots other than `keep`, and temporary directories a dead process left. Returns what was removed.

    Call it only when no run is live: a run of an earlier canopy may still be loading its snapshot.

    Returns:
        The directories removed, in name order; empty when there is no runtime directory.
    """
    runtime = state_dir / RUNTIME_DIR
    if not runtime.is_dir():
        return []
    removed: list[Path] = []
    now = time.time()
    for entry in sorted(runtime.iterdir()):
        if entry == keep or not entry.is_dir():
            continue
        if entry.name.startswith(_TMP_PREFIX) and now - entry.stat().st_mtime < _STALE_TMP_SECONDS:
            continue
        shutil.rmtree(entry, ignore_errors=True)
        removed.append(entry)
    return removed
