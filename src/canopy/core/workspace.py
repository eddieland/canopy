"""The workspace: the directory canopy runs from, the repositories its queue works in, and their pools (DESIGN §18).

A directory with a `canopy-workspace.toml` is a workspace. Its map names each repository, cloned at `repos/<name>`,
with a treehouse pool under `.treehouse/` and canopy's state under `.canopy/`. canopy runs only from a workspace, even
for one repository: it reads no config from a code repository (D016).

The map's `[workspace]` and `[repos]` tables are read here; its `[tracker]`, `[policy]`, and `[trust]` tables are the
shared config layer, read by `config.load`. Summaries and `MAP.md` are data, like ticket text: they help choose a
repository and authorize nothing. Clone URLs are read only by `canopy workspace sync`, never by a tick.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, StrictStr, ValidationError

from canopy.core import treehouse
from canopy.core.config import (
    WORKSPACE_FILE_NAME,
    WORKSPACE_MAP_TABLES,
    WORKSPACE_STATE_DIR,
    ConfigError,
    RepoName,
)
from canopy.infra import logs

MAP_FILE_NAME = "MAP.md"
# The shared config file earlier canopy read from a repository's root. It is never read now; finding one only adds a
# hint to the error that there is no workspace (D016).
OLD_REPO_FILE_NAME = "canopy.toml"
REPOS_DIR = "repos"
POOLS_DIR = ".treehouse"
DESKS_DIR = "desks"
MAX_SUMMARY = 200


def _summary(value: str) -> str:
    if len(value) > MAX_SUMMARY or "\n" in value or "\r" in value:
        raise ValueError(f"must be one line of at most {MAX_SUMMARY} characters")
    return value


def url_error(value: str) -> str | None:
    """Say why `value` cannot be a map's clone URL, or None if it can."""
    # The URL reaches `git clone`'s argv after `--`; refusing a leading "-" and blanks keeps it one plain argument.
    if not value.strip() or value.startswith("-") or any(c.isspace() for c in value):
        return "must be a clone URL: not empty, no whitespace, not starting with '-'"
    return None


def _url(value: str) -> str:
    error = url_error(value)
    if error is not None:
        raise ValueError(error)
    return value


class _Table(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _WorkspaceTable(_Table):
    name: RepoName | None = None


class _RepoTable(_Table):
    url: Annotated[StrictStr, AfterValidator(_url)]
    summary: Annotated[StrictStr, AfterValidator(_summary)] = ""


class _Map(_Table):
    workspace: _WorkspaceTable = _WorkspaceTable()
    repos: dict[RepoName, _RepoTable] = {}


@dataclass(frozen=True)
class Repo:
    """One repository in the map: its name, primary clone, clone URL, and summary."""

    name: str
    path: Path
    url: str | None = None
    summary: str = ""

    @property
    def cloned(self) -> bool:
        """Whether the primary clone is there. A tick never clones; `canopy workspace sync` does."""
        return (self.path / ".git").exists()


@dataclass(frozen=True)
class Workspace:
    """The root canopy runs from, its workspace file, and the repositories in it."""

    root: Path
    name: str
    repos: tuple[Repo, ...]
    map_file: Path

    @property
    def state_dir(self) -> Path:
        """Where the journal, locks, logs, and `attention.md` live: `.canopy/`, private to the operator."""
        return self.root.absolute() / WORKSPACE_STATE_DIR

    @property
    def map_prose(self) -> Path | None:
        """`MAP.md`, the prose the overseer reads about the repositories, if the workspace has one."""
        path = self.root / MAP_FILE_NAME
        return path if path.is_file() else None

    def repo(self, name: str | None) -> Repo | None:
        """Return the repository named `name`, or None if the map has none by that name."""
        if name is None:
            return None
        return next((r for r in self.repos if r.name == name), None)

    def pool(self, name: str | None) -> treehouse.Pool:
        """Return where treehouse runs for repository `name`'s pool.

        A workspace's pools are under its root, whichever `treehouse.toml` its repositories have. A repository with no
        clone gets the root as its working directory: `return` still finds a slot's pool from the slot's own path, so a
        run in it can be closed, though nothing new can be leased there.
        """
        repo = self.repo(name)
        cwd = repo.path if repo is not None and repo.cloned else self.root
        return treehouse.Pool(cwd=cwd, root=self.root)


def default_name(root: Path) -> str:
    """Name a workspace after its directory, reduced to a valid repository name, when its map names none."""
    return reduce_name(root.name) or "workspace"


def reduce_name(text: str) -> str:
    """Reduce `text` to a valid repository name: lowercased, other characters made hyphens. Empty if nothing is left."""
    reduced = re.sub(r"[^a-z0-9-]+", "-", text.lower()).strip("-")
    return reduced.lstrip("0123456789-")


def find_root(start: Path) -> Path | None:
    """Return the nearest directory at or above `start` holding a workspace file, or None."""
    start = start.resolve()
    for d in (start, *start.parents):
        if (d / WORKSPACE_FILE_NAME).is_file():
            return d
    return None


def find(start: Path) -> Workspace:
    """Return the workspace `start` is in: the one whose workspace file is nearest above it.

    Raises:
        ConfigError: there is none, or the workspace file does not load.
    """
    root = find_root(start)
    if root is None:
        raise ConfigError(no_workspace_message(start))
    return load(root)


def no_workspace_message(start: Path) -> str:
    """Say there is no workspace at or above `start`, and how to make one."""
    message = (
        f"no {WORKSPACE_FILE_NAME} here or above; canopy runs from a workspace. In an empty directory, run "
        f"`canopy init --provider <tracker> <clone URL>...` to make one."
    )
    old = _old_repo_file(start)
    if old is not None:
        message += f"\n{old} is not read: move its keys to {WORKSPACE_FILE_NAME} in the workspace (D016)."
    return message


def _old_repo_file(start: Path) -> Path | None:
    checkout = git_root(start)
    path = checkout / OLD_REPO_FILE_NAME if checkout is not None else None
    return path if path is not None and path.is_file() else None


def git_root(start: Path) -> Path | None:
    """The nearest directory at or above `start` holding `.git`, a directory or a worktree's file, or None."""
    start = start.resolve()
    return next((d for d in (start, *start.parents) if (d / ".git").exists()), None)


def load(root: Path) -> Workspace:
    """Read the map of the workspace at `root`.

    Raises:
        ConfigError: the workspace file is missing, not TOML, or its map is invalid. The message names the file.
    """
    path = root / WORKSPACE_FILE_NAME
    try:
        with path.open("rb") as f:
            doc = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    except OSError as e:
        raise ConfigError(f"{path}: {e.strerror}") from e
    try:
        parsed = _Map.model_validate({k: v for k, v in doc.items() if k in WORKSPACE_MAP_TABLES})
    except ValidationError as e:
        errors = [f"{path}: {'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]
        raise ConfigError("\n".join(errors)) from e
    repos = tuple(
        Repo(name=name, path=root / REPOS_DIR / name, url=table.url, summary=table.summary)
        for name, table in sorted(parsed.repos.items())
    )
    return Workspace(root=root, name=parsed.workspace.name or default_name(root), repos=repos, map_file=path)


def ensure_state_dir(state_dir: Path) -> None:
    """Create the state directory readable only by the operator, and refuse one canopy did not make.

    A workspace's state is inside its root, which may be a checkout of a shared repository. A `.canopy/` that came from
    the checkout could hold agent definitions or a journal someone else wrote, so it must be the operator's own and
    closed to everyone else, as canopy creates it (DESIGN §18).

    Raises:
        ConfigError: the workspace's state directory is not private to the operator.
    """
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if logs.private_dir(state_dir):
        return
    raise ConfigError(
        f"{state_dir} is not private to you: canopy creates it as a directory only you can read, and this one is a "
        f"symlink, someone else's, or open to others. If it came from a checkout, remove it; canopy recreates it."
    )
