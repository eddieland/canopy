"""The bench file: where each case's PR comes from, the repository it is opened in, and whose comments count.

A case is a `replay` of a PR as it was, from its base to its head, or an `undo_fix`: a commit that fixed a bug,
reversed on top of itself, so the PR brings back a bug that shipped once. A `bug` case names where its bug is, as
`path:line` or `path:first-last`, on the head's side (`lines`) or the base's (`base_lines`, for a line the PR
deletes); an `undo_fix` without either takes them from its diff. A `clean` case is a PR known to be sound, so every
comment on it is a false alarm.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, model_validator

#: A case's name: it names the case in results and in `--case`.
NAME_RE: Final = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
#: Where a bug is: `path:line`, or `path:first-last` for a range of lines.
SPOT_RE: Final = re.compile(r"(?P<path>[^\s:][^:]*):(?P<first>[1-9][0-9]{0,6})(?:-(?P<last>[1-9][0-9]{0,6}))?")
#: A full commit, as git names one: sha-1 or sha-256.
COMMIT_RE: Final = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
#: A GitHub repository, `owner/name`.
REPO_RE: Final = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


class BenchError(Exception):
    """The bench cannot go on: its file is not valid, or git or gh failed."""


class Side(StrEnum):
    """Which side of a PR's diff a line is numbered on."""

    #: The PR's head: lines it adds or keeps.
    HEAD = "head"
    #: Its base: lines it deletes.
    BASE = "base"


@dataclass(frozen=True)
class Spot:
    """A range of lines in one file, on one side of the diff."""

    path: str
    first: int
    last: int
    side: Side

    @classmethod
    def parse(cls, text: str, side: Side) -> Spot:
        """Read `text`, `path:line` or `path:first-last`, as a spot on `side`.

        Returns:
            The spot.

        Raises:
            ValueError: `text` is neither, or its range ends before it starts.
        """
        found = SPOT_RE.fullmatch(text)
        if found is None:
            raise ValueError(f"{text!r} must be path:line or path:first-last")
        first = int(found["first"])
        last = int(found["last"]) if found["last"] is not None else first
        if last < first:
            raise ValueError(f"{text!r} ends before it starts")
        return cls(found["path"], first, last, side)

    def near(self, path: str, first: int, last: int, side: Side, tolerance: int) -> bool:
        """Whether lines `first` to `last` of `path` on `side` are within `tolerance` lines of this spot.

        Returns:
            True when they overlap it, widened by `tolerance` on each side.
        """
        return (
            side == self.side
            and path == self.path
            and first - tolerance <= self.last
            and self.first <= last + tolerance
        )

    def __str__(self) -> str:
        """Return the spot as the bench file spells it, `path:first-last`, or `path:line` for one line."""
        lines = f"{self.first}" if self.first == self.last else f"{self.first}-{self.last}"
        return f"{self.path}:{lines}"


def _name(value: str) -> str:
    if not NAME_RE.fullmatch(value):
        raise ValueError(f"{value!r} must match {NAME_RE.pattern}")
    return value


def _commit(value: str) -> str:
    if not COMMIT_RE.fullmatch(value):
        raise ValueError(f"{value!r} must be a full commit: 40 or 64 lowercase hex characters")
    return value


def _spot(value: str) -> str:
    Spot.parse(value, Side.HEAD)
    return value


def _repo(value: str) -> str:
    if not REPO_RE.fullmatch(value):
        raise ValueError(f"{value!r} must be owner/name")
    return value


def _relative(value: str) -> str:
    parts = value.strip("/").split("/")
    if not value or value.startswith("/") or any(p in {"", ".", ".."} for p in parts):
        raise ValueError(f"{value!r} must be a path in the repository, such as .github/workflows")
    return value.strip("/")


Commit = Annotated[str, AfterValidator(_commit)]
SpotText = Annotated[str, AfterValidator(_spot)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Replay(_Model):
    """A PR as it was: the commit it left its base at, and its head."""

    #: Its merge base with the branch it merged into: for a merged PR, with that branch as it was just before.
    base: Commit
    head: Commit


class UndoFix(_Model):
    """A commit that fixed a bug, which the case's PR reverses."""

    fix: Commit
    #: The paths, and the directories, whose part of the fix is reversed; none for all of it. Leave the fix's tests
    #: out, so the PR does not delete the test that names the bug.
    paths: tuple[str, ...] = ()


class Case(_Model):
    """One `[[cases]]` table: a PR the reviewer is scored on."""

    name: Annotated[str, AfterValidator(_name)]
    kind: Literal["bug", "clean"]
    #: The PR's title, which is also its head commit's message: write it as your team would, without the bug.
    title: Annotated[str, Field(min_length=1, max_length=200)]
    #: The PR's description, as your team would write it.
    body: str = ""
    #: `holdout` for a case kept out of sight while the reviewer's instructions are tuned.
    split: Literal["tune", "holdout"] = "tune"
    replay: Replay | None = None
    undo_fix: UndoFix | None = None
    #: Where the bug is, numbered as the PR's head has it.
    lines: tuple[SpotText, ...] = ()
    #: Where the bug is, numbered as the PR's base has it: a line the PR deletes.
    base_lines: tuple[SpotText, ...] = ()

    @model_validator(mode="after")
    def _one_source(self) -> Self:
        if (self.replay is None) == (self.undo_fix is None):
            raise ValueError(f"case {self.name} needs one of replay or undo_fix")
        spots = self.lines or self.base_lines
        if self.kind == "clean" and spots:
            raise ValueError(f"clean case {self.name} has no bug, so no lines")
        if self.kind == "clean" and self.undo_fix is not None:
            raise ValueError(f"case {self.name} undoes a fix, so it is a bug case")
        if self.kind == "bug" and self.replay is not None and not spots:
            raise ValueError(f"bug case {self.name} needs lines or base_lines, where its bug is")
        return self

    @property
    def source(self) -> Literal["replay", "undo_fix"]:
        """Where the case's PR comes from."""
        return "replay" if self.replay is not None else "undo_fix"

    @property
    def spots(self) -> tuple[Spot, ...]:
        """Where its bug is, as the bench file names it: none on a clean case, or an `undo_fix` that leaves it out."""
        return (
            *(Spot.parse(t, Side.HEAD) for t in self.lines),
            *(Spot.parse(t, Side.BASE) for t in self.base_lines),
        )


class Settings(_Model):
    """The `[bench]` table."""

    #: A clone of the repository the cases come from, which holds every commit they name; relative to the bench file.
    source: Annotated[str, Field(min_length=1)]
    #: The repository on GitHub the PRs are opened in, `owner/name`, with the reviewer installed on it: a private
    #: copy if you can make one the reviewer covers, or the real repository.
    repo: Annotated[str, AfterValidator(_repo)]
    #: The GitHub host, for GitHub Enterprise.
    host: Annotated[str, Field(min_length=1)] = "github.com"
    #: Where the case's branches are pushed; `https://HOST/REPO.git` when unset.
    push_url: str | None = None
    #: The logins whose comments count as the reviewer's, such as `acme-review[bot]`.
    reviewers: Annotated[tuple[str, ...], Field(min_length=1)]
    #: How many lines from a bug's a comment may be and still find it.
    tolerance: Annotated[int, Field(ge=0, le=50)] = 3
    #: How long to wait for a review before a PR is scored as silent.
    wait_minutes: Annotated[int, Field(ge=1, le=24 * 60)] = 30
    #: How long the reviewer must post nothing new, once it has posted, before its review is taken as done.
    quiet_minutes: Annotated[int, Field(ge=0, le=60)] = 3
    #: How often GitHub is asked for the reviewer's comments while waiting.
    poll_seconds: Annotated[int, Field(ge=5, le=600)] = 30
    #: Paths, files or directories, removed from both of every case's commits, so a PR in a shared repository asks no
    #: code owner for a review and starts no workflow: such as `.github/CODEOWNERS` and `.github/workflows`.
    strip: tuple[Annotated[str, AfterValidator(_relative)], ...] = ()
    #: Whether each PR is opened as a draft, which asks no code owner for a review; only for a reviewer that reviews
    #: drafts.
    draft: bool = False

    @property
    def url(self) -> str:
        """Where the case's branches are pushed."""
        return self.push_url or f"https://{self.host}/{self.repo}.git"


class BenchFile(_Model):
    """A bench file: its settings and its cases."""

    bench: Settings
    cases: Annotated[tuple[Case, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _distinct(self) -> Self:
        names = [c.name for c in self.cases]
        twice = sorted({n for n in names if names.count(n) > 1})
        if twice:
            raise ValueError(f"case names {', '.join(twice)} are used more than once")
        return self


@dataclass(frozen=True)
class Loaded:
    """A bench file read, and where its paths are relative to."""

    file: BenchFile
    #: The directory the bench file is in, which results are saved under.
    root: Path

    @property
    def source(self) -> Path:
        """The source clone, resolved against the bench file's directory."""
        return (self.root / self.file.bench.source).resolve()


def load(path: Path) -> Loaded:
    """Read and check the bench file at `path`.

    Returns:
        The bench, with the directory it is in.

    Raises:
        BenchError: it cannot be read, is not TOML, or is not a valid bench.
    """
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise BenchError(f"{path}: {e}") from e
    try:
        bench = BenchFile.model_validate(data)
    except ValidationError as e:
        raise BenchError(f"{path}: {e}") from e
    return Loaded(bench, path.resolve().parent)


def chosen(cases: tuple[Case, ...], names: tuple[str, ...], split: str | None) -> list[Case]:
    """Return the cases `names` names, or every one without, in the file's order, of `split` when it is given.

    Returns:
        The cases.

    Raises:
        BenchError: a name is no case's, or no case is left.
    """
    unknown = sorted(set(names) - {c.name for c in cases})
    if unknown:
        raise BenchError(f"no case named {', '.join(unknown)}")
    found = [c for c in cases if (not names or c.name in names) and (split is None or c.split == split)]
    if not found:
        raise BenchError("no case is left to run")
    return found
