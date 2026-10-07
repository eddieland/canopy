"""The workspace: the directory canopy runs from, the repositories its queue works in, and their pools (DESIGN §18).

A directory with a `canopy-workspace.toml` is a workspace. Its map names each repository, cloned at `repos/<name>`,
with a treehouse pool under `.treehouse/` and canopy's state under `.canopy/`. A repository with no workspace file
above it is a workspace of one: the repository itself, with its `canopy.toml` as the shared config layer, and its pool
and state where treehouse and `paths.state_dir` put them. Code takes a `Workspace` and has one path for both.

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
from canopy.core.config import REPO_NAME_RE, WORKSPACE_FILE_NAME, WORKSPACE_MAP_TABLES, ConfigError, find_repo_root
from canopy.infra import logs

MAP_FILE_NAME = "MAP.md"
REPOS_DIR = "repos"
POOLS_DIR = ".treehouse"
DESKS_DIR = "desks"
MAX_SUMMARY = 200


def _repo_name(value: str) -> str:
    if not REPO_NAME_RE.fullmatch(value):
        raise ValueError(f"repository name {value!r} must match {REPO_NAME_RE.pattern}")
    return value


def _summary(value: str) -> str:
    if len(value) > MAX_SUMMARY or "\n" in value or "\r" in value:
        raise ValueError(f"must be one line of at most {MAX_SUMMARY} characters")
    return value


def _url(value: str) -> str:
    # The URL reaches `git clone`'s argv after `--`; refusing a leading "-" and blanks keeps it one plain argument.
    if not value.strip() or value.startswith("-") or any(c.isspace() for c in value):
        raise ValueError("must be a clone URL: not empty, no whitespace, not starting with '-'")
    return value


class _Table(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _WorkspaceTable(_Table):
    name: Annotated[StrictStr, AfterValidator(_repo_name)] | None = None


class _RepoTable(_Table):
    url: Annotated[StrictStr, AfterValidator(_url)]
    summary: Annotated[StrictStr, AfterValidator(_summary)] = ""


class _Map(_Table):
    workspace: _WorkspaceTable = _WorkspaceTable()
    repos: dict[Annotated[str, AfterValidator(_repo_name)], _RepoTable] = {}


@dataclass(frozen=True)
class Repo:
    """One repository in the map: its name, primary clone, clone URL, and summary. A workspace of one has no URL."""

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
    """The root canopy runs from and the repositories in it.

    `map_file` is the workspace file, or None for a workspace of one, whose only repository is the root.
    """

    root: Path
    name: str
    repos: tuple[Repo, ...]
    map_file: Path | None = None

    @property
    def single(self) -> bool:
        """Whether this is a workspace of one: a repository with no workspace file."""
        return self.map_file is None

    @property
    def map_prose(self) -> Path | None:
        """`MAP.md`, the prose the overseer reads about the repositories, if the workspace has one."""
        path = self.root / MAP_FILE_NAME
        return path if not self.single and path.is_file() else None

    def repo(self, name: str | None) -> Repo | None:
        """Return the repository named `name`. None names a workspace of one's only repository."""
        if name is None:
            return self.repos[0] if self.single else None
        return next((r for r in self.repos if r.name == name), None)

    def pool(self, name: str | None) -> treehouse.Pool:
        """Return where treehouse runs for repository `name`'s pool.

        A workspace's pools are under its root, whichever `treehouse.toml` its repositories have. A repository with no
        clone gets the root as its working directory: `return` still finds a slot's pool from the slot's own path, so a
        run in it can be closed, though nothing new can be leased there.
        """
        repo = self.repo(name)
        if self.single:
            return treehouse.Pool(cwd=self.root)
        cwd = repo.path if repo is not None and repo.cloned else self.root
        return treehouse.Pool(cwd=cwd, root=self.root)


def of_one(repo_root: Path) -> Workspace:
    """Return the workspace of one for the repository at `repo_root`."""
    name = one_name(repo_root)
    return Workspace(root=repo_root, name=name, repos=(Repo(name=name, path=repo_root),))


def one_name(repo_root: Path) -> str:
    """Name a workspace of one's repository after its directory, reduced to a valid repository name."""
    reduced = re.sub(r"[^a-z0-9-]+", "-", repo_root.name.lower()).strip("-")
    reduced = reduced.lstrip("0123456789-")
    return reduced or "repo"


def find_root(start: Path) -> Path | None:
    """Return the nearest directory at or above `start` holding a workspace file, or None."""
    start = start.resolve()
    for d in (start, *start.parents):
        if (d / WORKSPACE_FILE_NAME).is_file():
            return d
    return None


def find(start: Path) -> Workspace:
    """Return the workspace `start` is in: the nearest workspace file above it, else the repository it is in.

    Raises:
        ConfigError: neither is found, or the workspace file does not load.
    """
    root = find_root(start)
    return load(root) if root is not None else of_one(find_repo_root(start))


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
    return Workspace(root=root, name=parsed.workspace.name or one_name(root), repos=repos, map_file=path)


def ensure_state_dir(workspace: Workspace, state_dir: Path) -> None:
    """Create the state directory readable only by the operator, and refuse one canopy did not make.

    A workspace's state is inside its root, which may be a checkout of a shared repository. A `.canopy/` that came from
    the checkout could hold agent definitions or a journal someone else wrote, so it must be the operator's own and
    closed to everyone else, as canopy creates it (DESIGN §18). A workspace of one keeps its state where
    `paths.state_dir` says, outside any checkout.

    Raises:
        ConfigError: the workspace's state directory is not private to the operator.
    """
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if workspace.single or logs.private_dir(state_dir):
        return
    raise ConfigError(
        f"{state_dir} is not private to you: canopy creates it as a directory only you can read, and this one is a "
        f"symlink, someone else's, or open to others. If it came from a checkout, remove it; canopy recreates it."
    )
