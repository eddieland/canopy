"""The mirror on GitHub, through `gh api`: open a case's PR, read what was said on it, close it, delete its branches.

gh holds the token, so the bench never does: sign in with `gh auth login`, on the mirror's host.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from canopy_review_bench import command
from canopy_review_bench.bench import BenchError, Side

if TYPE_CHECKING:
    from collections.abc import Mapping


class Comment(BaseModel):
    """One thing someone said on a PR."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: `inline` for a comment on lines of the diff, `review` for a review's body, `conversation` for the PR's thread.
    kind: Literal["inline", "review", "conversation"]
    author: str
    body: str
    #: Its creation time, as GitHub gives it.
    at: str
    #: An inline comment's file, first and last line, and the side of the diff they are numbered on.
    path: str | None = None
    first: int | None = None
    last: int | None = None
    side: Side | None = None

    @property
    def located(self) -> bool:
        """Whether it is on lines of the diff, so it can be scored as a finding."""
        return self.path is not None and self.first is not None and self.last is not None and self.side is not None


class GitHub:
    """The mirror, `owner/name` on `host`."""

    def __init__(self, repo: str, host: str) -> None:
        """Name the mirror: `repo`, `owner/name`, on `host`."""
        self._repo = repo
        self._host = host

    def open_pr(self, *, base: str, head: str, title: str, body: str) -> int:
        """Open a PR from branch `head` into branch `base`.

        Returns:
            Its number.

        Raises:
            BenchError: gh failed, or said something that is not a PR.
        """
        fields = {"base": base, "head": head, "title": title, "body": body}
        made = _parse(_Pull, self._api("POST", f"repos/{self._repo}/pulls", fields=fields))
        return made.number

    def comments(self, number: int) -> list[Comment]:
        """Return everything said on PR `number`: its inline comments that open a thread, reviews' bodies, and talk.

        A reply in a thread is not a finding of its own, so it is left out.

        Returns:
            The comments, inline ones first, each kind in GitHub's order.

        Raises:
            BenchError: gh failed, or said something that is not what was asked.
        """
        pull = f"repos/{self._repo}/pulls/{number}"
        found: list[Comment] = []
        for raw in self._pages(f"{pull}/comments"):
            c = _parse(_Inline, raw)
            if c.in_reply_to_id is None:
                last = c.line or c.original_line
                first = c.start_line or c.original_start_line or last
                side = Side.BASE if c.side == "LEFT" else Side.HEAD
                found.append(
                    Comment(
                        kind="inline",
                        author=c.user.login,
                        body=c.body,
                        at=c.created_at,
                        path=c.path,
                        first=first,
                        last=last,
                        side=side if last is not None else None,
                    ),
                )
        for raw in self._pages(f"{pull}/reviews"):
            r = _parse(_Review, raw)
            if r.body:
                found.append(Comment(kind="review", author=r.user.login, body=r.body, at=r.submitted_at or ""))
        for raw in self._pages(f"repos/{self._repo}/issues/{number}/comments"):
            i = _parse(_Said, raw)
            found.append(Comment(kind="conversation", author=i.user.login, body=i.body, at=i.created_at))
        return found

    def close(self, number: int) -> None:
        """Close PR `number`.

        Raises:
            BenchError: gh failed.
        """
        self._api("PATCH", f"repos/{self._repo}/pulls/{number}", fields={"state": "closed"})

    def delete_branch(self, branch: str) -> None:
        """Delete `branch` from the mirror.

        Raises:
            BenchError: gh failed.
        """
        self._api("DELETE", f"repos/{self._repo}/git/refs/heads/{branch}")

    def _pages(self, path: str) -> list[object]:
        pages = self._api("GET", f"{path}?per_page=100", paginate=True)
        if not isinstance(pages, list):
            raise BenchError(f"gh api {path}: not a list of pages")
        found: list[object] = []
        for page in pages:
            if not isinstance(page, list):
                raise BenchError(f"gh api {path}: a page is not a list")
            found.extend(page)
        return found

    def _api(
        self,
        method: Literal["GET", "POST", "PATCH", "DELETE"],
        path: str,
        *,
        fields: Mapping[str, str] | None = None,
        paginate: bool = False,
    ) -> object:
        """Call GitHub's REST API through gh, and return what it answered, `--slurp`ed into a list of pages if paged.

        Returns:
            The answer's JSON, or None for an empty one.

        Raises:
            BenchError: gh failed, or its answer is not JSON.
        """
        argv = ["gh", "api", "--hostname", self._host, "--method", method, path]
        for key, value in (fields or {}).items():
            argv += ["--raw-field", f"{key}={value}"]
        if paginate:
            argv += ["--paginate", "--slurp"]
        out = command.run(argv)
        try:
            return json.loads(out) if out.strip() else None
        except json.JSONDecodeError as e:
            raise BenchError(f"gh api {path}: not JSON: {e}") from e


class _Gh(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class _User(_Gh):
    login: str


class _Pull(_Gh):
    number: int


class _Inline(_Gh):
    user: _User
    body: str
    created_at: str
    path: str
    line: int | None = None
    original_line: int | None = None
    start_line: int | None = None
    original_start_line: int | None = None
    side: str | None = None
    in_reply_to_id: int | None = None


class _Review(_Gh):
    user: _User
    body: str | None = None
    submitted_at: str | None = None


class _Said(_Gh):
    user: _User
    body: str = Field(default="")
    created_at: str


def _parse[M: _Gh](model: type[M], raw: object) -> M:
    try:
        return model.model_validate(raw)
    except ValidationError as e:
        raise BenchError(f"gh answered something that is not a {model.__name__.lstrip('_').lower()}: {e}") from e
