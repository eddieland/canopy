"""The workspace: the directory canopy runs from, the repositories its queue works in, and their pools (DESIGN §18).

A directory with a `canopy-workspace.toml` is a workspace. Its map names each repository, cloned at `repos/<name>`,
with a treehouse pool under `.treehouse/` and canopy's state under `.canopy/`. canopy runs only from a workspace, even
for one repository: it reads no config from a code repository (D016).

The map's `[workspace]` and `[repos]` tables are read here; its `[tracker]`, `[policy]`, and `[trust]` tables are the
shared config layer, read by `config.load`. Summaries and `MAP.md` are data, like ticket text: they help choose a
repository and authorize nothing. Clone URLs are read only by `canopy workspace sync`, never by a tick, and to make the
web UI's branch links. A branch URL is only ever a link.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictStr, ValidationError, model_validator

from canopy.core import hostgit, treehouse
from canopy.core.config import (
    WORKSPACE_FILE_NAME,
    WORKSPACE_MAP_TABLES,
    WORKSPACE_STATE_DIR,
    ConfigError,
    RepoName,
    link_template,
)
from canopy.infra import logs

MAP_FILE_NAME: Final = "MAP.md"
# The shared config file earlier canopy read from a repository's root. It is never read now; finding one only adds a
# hint to the error that there is no workspace (D016).
OLD_REPO_FILE_NAME: Final = "canopy.toml"
REPOS_DIR: Final = "repos"
POOLS_DIR: Final = ".treehouse"
DESKS_DIR: Final = "desks"
MAX_SUMMARY: Final = 200
#: The longest name of a check a repository's `checks` names: a connector's longest (DESIGN §30).
MAX_CHECK_NAME: Final = 200
# Where a repository's `branch_url` puts a branch's name.
BRANCH_NAME: Final = "{branch}"
# A GitHub clone URL as `git clone` takes it: https (credentials allowed, and dropped), scp-style SSH, or ssh://, with
# an optional `.git` and trailing slash. Its owner and repository name make the default `branch_url` (D115).
GITHUB_URL_RE: Final = re.compile(
    r"(?:https://(?:[^@/\s]+@)?|ssh://git@|git@)github\.com[/:]([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?",
    re.IGNORECASE,
)


class CheckRole(StrEnum):
    """What a check at a PR's head means to canopy, as its repository's map says (DESIGN §30). Unnamed, it is CI."""

    #: CI: it holds the PR at `ci_running` while pending, makes it `ci_red` failing, and has to pass.
    CI = "ci"
    #: It waits on a person, such as an ownership or deploy approval: shown with the checks, never CI.
    HUMAN = "human"
    #: It gates the merge itself, such as a merge queue's status, never green on an open PR: left out of the checks.
    MERGE = "merge"
    #: Advisory or retired: left out of the checks.
    IGNORE = "ignore"


def _summary(value: str) -> str:
    if len(value) > MAX_SUMMARY or "\n" in value or "\r" in value:
        raise ValueError(f"must be one line of at most {MAX_SUMMARY} characters")
    return value


def url_error(value: str) -> str | None:
    """Say why `value` cannot be a map's clone URL, or None if it can.

    Returns:
        The reason, for an error message, or None.
    """
    # The URL reaches `git clone`'s argv after `--`; refusing a leading "-" and blanks keeps it one plain argument.
    if not value.strip() or value.startswith("-") or any(c.isspace() for c in value):
        return "must be a clone URL: not empty, no whitespace, not starting with '-'"
    return None


def _check_name(value: str) -> str:
    if not value.strip() or len(value) > MAX_CHECK_NAME or not value.isprintable():
        raise ValueError(f"must be a check's name: printable, 1 to {MAX_CHECK_NAME} characters")
    return value


def _impact_path(value: str) -> str:
    # Compared with the paths git names, which are from the root, by whole components (`canopy.reviews.impact`).
    parts = value.removesuffix("/").split("/")
    if not value.isprintable() or value.startswith("/") or any(p in {"", ".", ".."} for p in parts):
        raise ValueError(
            "must be a path from the repository's root, such as '.agents/' or 'docs/TRUST_MODEL.md', with no leading "
            "'/', empty part, '.', or '..'",
        )
    return value


def _url(value: str) -> str:
    error = url_error(value)
    if error is not None:
        raise ValueError(error)
    return value


class _Table(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)


class _WorkspaceTable(_Table):
    name: RepoName | None = None


class _RepoTable(_Table):
    url: Annotated[StrictStr, AfterValidator(_url)]
    summary: Annotated[StrictStr, AfterValidator(_summary)] = ""
    # A branch's page on the repository's host, with {branch} where its name goes: the web UI links branches there
    # (DESIGN §18). Unset means the one `url` gives on GitHub, if any; empty means no link.
    branch_url: Annotated[StrictStr, link_template(BRANCH_NAME)] | None = None
    # The role of each check named, by its exact name; every other check is CI (DESIGN §30).
    checks: dict[Annotated[StrictStr, AfterValidator(_check_name)], CheckRole] = {}
    # Paths whose change makes a review high impact, beside CI's workflows, which no entry removes (DESIGN §21).
    high_impact_paths: tuple[Annotated[StrictStr, AfterValidator(_impact_path)], ...] = ()

    @model_validator(mode="before")
    @classmethod
    def _no_human_checks(cls, data: object) -> object:
        # The list `checks` replaced: an error that says what to write, not "extra inputs are not permitted".
        if isinstance(data, Mapping) and "human_checks" in data:
            raise ValueError(
                'human_checks was removed: name each of its checks in `checks` instead, as "NAME" = "human" under '
                "[repos.<name>.checks]",
            )
        return data


class _Map(_Table):
    workspace: _WorkspaceTable = Field(default_factory=_WorkspaceTable)
    repos: dict[RepoName, _RepoTable] = {}


@dataclass(frozen=True)
class Repo:
    """One repository in the map: its name, primary clone, clone URL, summary, and where its branches' pages are."""

    name: str
    path: Path
    url: str | None = None
    summary: str = ""
    branch_url: str = ""
    #: The role of each check its map names, by exact name: every other check is CI (DESIGN §30).
    checks: Mapping[str, CheckRole] = field(default_factory=dict[str, CheckRole])
    #: The paths from the root, each covering itself and everything under it, whose change makes a review of this
    #: repository `high` impact. They add to `.github/workflows/`, which covers every repository (DESIGN §21).
    high_impact_paths: Sequence[str] = ()

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

    def check_roles(self, name: str | None) -> Mapping[str, CheckRole]:
        """Return the roles repository `name` gives its checks, by name: none for a repository the map does not have.

        Returns:
            The roles. A check they do not name is CI: read one as `check_roles(name).get(check, CheckRole.CI)`.
        """
        repo = self.repo(name)
        return repo.checks if repo is not None else {}

    def treehouse_pool(self, name: str | None) -> treehouse.Pool:
        """Return where treehouse runs for repository `name`'s pool.

        A workspace's pools are under its root, whichever `treehouse.toml` its repositories have. A repository with no
        clone gets the root as its working directory: `return` still finds a slot's pool from the slot's own path, so a
        run in it can be closed, though nothing new can be leased there.
        """
        repo = self.repo(name)
        clone = repo.path if repo is not None else (self.root / REPOS_DIR / name if name else None)
        # A clone the map no longer lists still has its pool, which sync empties before it removes the clone.
        cwd = clone if clone is not None and (clone / ".git").exists() else self.root
        return treehouse.Pool(cwd=cwd, root=self.root)


def default_name(root: Path) -> str:
    """Name a workspace after its directory, reduced to a valid repository name, when its map names none.

    Returns:
        The directory's name reduced by `reduce_name`, or `workspace` if nothing of it is left.
    """
    return reduce_name(root.name) or "workspace"


def reduce_name(text: str) -> str:
    """Reduce `text` to a valid repository name: lowercased, other characters made hyphens. Empty if nothing is left.

    Returns:
        The name, with no leading digits or hyphens and no trailing hyphens, or an empty string.
    """
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
    """Say there is no workspace at or above `start`, and how to make one.

    Returns:
        The error message, with a hint to move an old `canopy.toml`'s keys when the checkout has one.
    """
    message = (
        f"no {WORKSPACE_FILE_NAME} here or above; canopy runs from a workspace. In an empty directory, run "
        f"`canopy init --provider <tracker> <clone URL>...` to make one."
    )
    old = old_repo_file(start)
    if old is not None:
        message += f"\n{old} is not read: move its keys to {WORKSPACE_FILE_NAME} in the workspace (D016)."
    return message


def old_repo_file(start: Path) -> Path | None:
    """The `canopy.toml` at the root of the checkout `start` is in, if there is one. It is never read (D016).

    Returns:
        The file's path, or None if `start` is in no checkout or its root has no such file.
    """
    checkout = hostgit.git_root(start)
    path = checkout / OLD_REPO_FILE_NAME if checkout is not None else None
    return path if path is not None and path.is_file() else None


def load(root: Path) -> Workspace:
    """Read the map of the workspace at `root`.

    Returns:
        The workspace, named by its map or after its directory, with each repository the map lists.

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
        Repo(
            name=name,
            path=root / REPOS_DIR / name,
            url=table.url,
            summary=table.summary,
            branch_url=github_branch_url(table.url) if table.branch_url is None else table.branch_url,
            checks=table.checks,
            high_impact_paths=table.high_impact_paths,
        )
        for name, table in sorted(parsed.repos.items())
    )
    return Workspace(root=root, name=parsed.workspace.name or default_name(root), repos=repos, map_file=path)


def github_branch_url(url: str) -> str:
    """The branch link template a GitHub clone URL implies, for a repository whose map sets no `branch_url` (D115).

    Returns:
        `https://github.com/OWNER/REPO/tree/{branch}`, or an empty string, meaning no link, for any other URL.
    """
    match = GITHUB_URL_RE.fullmatch(url)
    if match is None or match[2] in {".", ".."}:
        return ""
    return f"https://github.com/{match[1]}/{match[2]}/tree/{BRANCH_NAME}"


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
        f"symlink, someone else's, or open to others. If it came from a checkout, remove it; canopy recreates it.",
    )
