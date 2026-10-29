"""The directory agent runs load canopy's agent definitions and skills from (DESIGN §13, D040).

canopy snapshots its bundled agents, skills, and plugins, with the git hooks that put its trailers on a worker's
commits (`commit_hooks`), into `<state_dir>/runtime/<digest>/`, named for a digest of their contents. A snapshot is
written to a temporary directory and renamed into place, so a run never sees a partial one. Command templates name it
with `{definitions_dir}`, and the runtime reads it as its config directory.

A snapshot is unwritable once written, by the operator too, and gets its write permission back only to be removed: the
runtime installs a package for its plugins into each config directory it can write, and waits on the registry for it
before a session starts (DESIGN §33). Nothing is installed into one it cannot write.

Some definitions are rendered from config: what canopy decides here, from config, that each agent may do
(`canopy.runtime.agents.Rules`), each agent's model among it, the runtime package writes in its own format, with a
copy of the chore's definition for each chore with a model of its own. The digest covers the rendered text, so a
config or override change makes a new snapshot rather than changing one a run may be loading, and each set of models
gets a snapshot of its own: a run whose ticket chose its agent's model renders that one in place of config's.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import stat
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import agent_models, bash_allows, commit_hooks, prompts, replies
from canopy.core.config import NO_TEMPERATURE
from canopy.core.vocab import ReplyMode, RunKind
from canopy.infra import logs
from canopy.runtime import agents
from canopy.runtime import definitions as runtime_definitions
from canopy.runtime.agents import DefinitionsError
from canopy.runtime.implementation import Version

if TYPE_CHECKING:
    from collections.abc import Mapping

    from canopy.core.config import Config
    from canopy.runtime.agents import Model

# Kept importable from here: the features catch `DefinitionsError` as the snapshot's.
__all__ = ["RUNTIME_DIR", "DefinitionsError", "digest", "ensure", "prune", "rules", "sources"]

RUNTIME_DIR = "runtime"
_TMP_PREFIX = ".tmp-"
# A temporary directory this old belongs to a process that died mid-copy; a copy takes well under a second.
_STALE_TMP_SECONDS = 3600


def sources(config: Config | None = None, models: Mapping[str, Model] | None = None) -> dict[str, bytes]:
    """Return the snapshot's files by relative path.

    They are the bundled agents and skills, with the workers', the reviewer's, and the overseer's definitions rendered
    from `config` when it is given, and canopy's git hooks. `models`, each agent's model by its name, takes the place
    of `runtime.models`' (`rules`).

    Raises:
        DefinitionsError: The overseer's prompt cannot be rendered, or a shipped definition cannot be rendered.
    """
    found = runtime_definitions.bundled(version=_version(config))
    rendered = found if config is None else runtime_definitions.render(found, rules(config, models))
    # The runtime reads none of them: they are here so that every run, a sandboxed one too, can read them (§24).
    return rendered | commit_hooks.files()


# The runtime `config` runs, or the default without one.
def _version(config: Config | None) -> Version:
    return Version.ONE if config is None else config.runtime.version


def rules(config: Config, models: Mapping[str, Model] | None = None) -> agents.Rules:
    """Return what `config` lets each agent do, for the runtime to write into its definitions.

    `models` is each agent's model by its name, in place of `runtime.models`', for a run whose ticket chose its agent's
    (`canopy.core.agent_models.of_run`); None takes config's.

    Raises:
        DefinitionsError: The overseer's prompt cannot be rendered (`prompts.render_overseer`).
    """
    try:
        prompt = prompts.render_overseer(config)
    except prompts.PromptError as e:
        raise DefinitionsError(str(e)) from e
    runtime = config.runtime
    # A chore with a model of its own runs a copy of the chore's agent made for it (DESIGN §19).
    chore_models = agent_models.chores(config)
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
        bash_allows=bash_allows.by_agent(runtime.allow_bash),
        artifacts=config.artifacts.publishing(),
        models=agent_models.by_agent(runtime.models, chore_models) if models is None else models,
        chore_agents=[agents.chore_agent(name) for name in sorted(chore_models)],
        tracker_server=config.tracker.server(),
    )


def _drafts(config: Config, *, private: bool) -> agents.Drafts:
    replied = replies.render(config, RunKind.RESUME, private=private)
    approve = replied is not None and replied.mode is ReplyMode.APPROVE
    # A public worker without a ticket's draft posts its ticket comments itself; a private one posts none.
    return agents.Drafts(
        approve=approve,
        ticket_comments=not private and not (replied is not None and replied.ticket_drafts),
    )


def digest(config: Config | None = None, models: Mapping[str, Model] | None = None) -> str:
    """Return a digest of the snapshot's files, their relative paths and contents, and of the links it holds."""
    return _digest(sources(config, models), runtime_definitions.links(version=_version(config)))


def _digest(files: Mapping[str, bytes], links: Mapping[str, Path]) -> str:
    h = hashlib.sha256()
    for rel, data in sorted(files.items()):
        h.update(f"{rel}\0{len(data)}\0".encode())
        h.update(data)
    # A link is its target's path, not the operator's file: their config changes no snapshot.
    for rel, target in sorted(links.items()):
        h.update(f"{rel}\0->{target}\0".encode())
    return h.hexdigest()[:16]


def ensure(state_dir: Path, config: Config | None = None, models: Mapping[str, Model] | None = None) -> Path:
    """Return the snapshot for the installed canopy and `config`, creating it, unwritable, if missing.

    `models`, each agent's model by its name, takes the place of `runtime.models`', as `rules` says.

    Safe to call from concurrent processes.

    canopy creates a snapshot readable only by the operator. One that is not was put there by something else, such as a
    checkout of a shared workspace (DESIGN §18), and could loosen canopy's agents, so it is refused, never loaded.

    Raises:
        DefinitionsError: the snapshot's directory exists and is not private to the operator, or the overseer's prompt
            cannot be rendered.
        OSError: the snapshot could not be written, and no other process put one in its place.
    """
    files = sources(config, models)
    links = runtime_definitions.links(version=_version(config))
    runtime = state_dir / RUNTIME_DIR
    final = runtime / _digest(files, links)
    if final.is_dir() or final.is_symlink():
        return _checked(final)
    runtime.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=_TMP_PREFIX, dir=runtime))
    try:
        for rel, data in files.items():
            path = tmp / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            if commit_hooks.is_hook(rel):
                path.chmod(0o700)
        # Links to the operator's own config, which the runtime reads through them; left as they are below.
        for rel, target in links.items():
            (tmp / rel).symlink_to(target)
        # Before the rename, so no run ever loads it writable. Renamed within its parent, it needs no write of its own.
        _set_writable(tmp, writable=False)
        os.rename(tmp, final)  # noqa: PTH104  (os.rename, unlike Path.replace, never replaces a non-empty directory)
    except OSError:
        _remove(tmp)
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
        _remove(entry)
        removed.append(entry)
    return removed


def _remove(snapshot: Path) -> None:
    """Remove `snapshot`, a snapshot or a temporary one, giving its directories their write permission back first.

    What cannot be removed is left, as `shutil.rmtree` with `ignore_errors` leaves it.
    """
    with contextlib.suppress(OSError):
        _set_writable(snapshot, writable=True)
    shutil.rmtree(snapshot, ignore_errors=True)


def _set_writable(root: Path, *, writable: bool) -> None:
    """Give `root` and every directory and file under it the owner's write permission, or take everyone's away.

    Symlinks are neither followed nor changed, `root` among them: those canopy writes into a snapshot lead to the
    operator's own config, which stays theirs to change.

    Raises:
        OSError: a permission could not be changed.
    """
    if root.is_symlink():
        return
    for here, _, names in os.walk(root):
        for path in (Path(here), *(Path(here) / name for name in names)):
            if path.is_symlink():
                continue
            mode = stat.S_IMODE(path.lstat().st_mode)
            path.chmod(mode | stat.S_IWUSR if writable else mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
