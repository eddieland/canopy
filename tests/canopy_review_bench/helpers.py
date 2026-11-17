"""What the review bench's tests share: a source repository with a PR and a fix in it, a bench file, a fake GitHub."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal
from unittest import mock

from canopy_review_bench.github import GitHub
from canopy_review_bench.run import Clock

from tests.conftest import git

#: The reviewer whose comments count.
BOT: Final = "review-bot[bot]"
#: The repository the PRs are opened in.
REPO: Final = "acme/api-bench"

BEFORE: Final = """\
def fetch(get, attempts):
    last = None
    for _ in range(attempts):
        try:
            return get()
        except TimeoutError as e:
            last = e
    raise last
"""
# The PR: a delay between attempts.
PR_HEAD: Final = """\
import time


def fetch(get, attempts, delay=0.1):
    last = None
    for _ in range(attempts):
        try:
            return get()
        except TimeoutError as e:
            last = e
            time.sleep(delay)
    raise last
"""
# The fix: no attempts at all raised None. Lines 5 and 6 are the guard.
FIXED: Final = """\
import time


def fetch(get, attempts, delay=0.1):
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    last = None
    for _ in range(attempts):
        try:
            return get()
        except TimeoutError as e:
            last = e
            time.sleep(delay)
    raise last
"""
FIX_TEST: Final = """\
def test_no_attempts():
    pass
"""


@dataclass(frozen=True)
class Source:
    """A source repository: a base, a PR's head on it, and a fix after it that adds a guard and its test.

    Its base has a CODEOWNERS file and a CI workflow, as a shared repository would.
    """

    path: Path
    base: str
    head: str
    fix: str


def source_repo(tmp_path: Path) -> Source:
    """Make the source repository under `tmp_path`.

    Returns:
        It, with its commits.
    """
    path = tmp_path / "source"
    path.mkdir()
    git("init", "--quiet", "--initial-branch=main", cwd=path)
    for directory in ("src", "tests", ".github/workflows"):
        (path / directory).mkdir(parents=True)
    shared = {".github/CODEOWNERS": "* @acme/api\n", ".github/workflows/ci.yml": "on: [push, pull_request]\n"}
    base = _commit(path, {"src/retry.py": BEFORE, **shared}, "Add fetch")
    head = _commit(path, {"src/retry.py": PR_HEAD}, "Wait between attempts")
    fix = _commit(path, {"src/retry.py": FIXED, "tests/test_retry.py": FIX_TEST}, "fix: refuse zero attempts")
    return Source(path, base, head, fix)


def _commit(path: Path, files: Mapping[str, str], message: str) -> str:
    for name, text in files.items():
        (path / name).write_text(text)
    git("add", "--all", cwd=path)
    git("commit", "--quiet", "-m", message, cwd=path)
    return git("rev-parse", "HEAD", cwd=path)


def bench_file(tmp_path: Path, cases: str, **settings: object) -> Path:
    """Write a bench file under `tmp_path`, its source the `source` directory beside it, with `cases` as TOML.

    `settings` are added to, or replace, the `[bench]` table's keys.

    Returns:
        Its path.
    """
    keys: dict[str, object] = {"source": "source", "repo": REPO, "reviewers": [BOT], **settings}
    lines = ["[bench]", *(f"{k} = {_toml(v)}" for k, v in keys.items()), "", cases]
    path = tmp_path / "bench.toml"
    path.write_text("\n".join(lines) + "\n")
    return path


def _toml(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, list):
        return "[" + ", ".join(_toml(v) for v in value) + "]"
    return str(value)


def inline(
    path: str,
    line: int,
    *,
    login: str = BOT,
    side: Literal["LEFT", "RIGHT"] = "RIGHT",
    start_line: int | None = None,
    reply_to: int | None = None,
) -> dict[str, object]:
    """Return an inline review comment as GitHub's REST API gives one.

    Returns:
        The comment's JSON.
    """
    return {
        "user": {"login": login},
        "body": f"something is wrong at {path}:{line}",
        "created_at": "2026-10-25T12:00:00Z",
        "path": path,
        "line": line,
        "start_line": start_line,
        "side": side,
        "in_reply_to_id": reply_to,
    }


def said(body: str, *, login: str = BOT) -> dict[str, object]:
    """Return a comment on a PR's conversation as GitHub's REST API gives one.

    Returns:
        The comment's JSON.
    """
    return {"user": {"login": login}, "body": body, "created_at": "2026-10-25T12:00:00Z"}


#: What the fake reviewer has said on a PR by the time of a poll: given the PR's title and how many times its
#: comments were read before, the inline comments, reviews, and conversation comments, each as GitHub gives them.
Reviewer = Callable[[str, int], Mapping[str, Sequence[dict[str, object]]]]


@dataclass
class FakeGitHub:
    """GitHub's REST API for the repository, as the bench calls it through gh."""

    reviewer: Reviewer
    #: Fails a call whose method and path start with this, as gh failing would.
    fails: str | None = None
    #: Each PR opened, by number: the fields it was opened with.
    opened: dict[int, Mapping[str, str | bool]] = field(default_factory=dict)
    closed: list[int] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    _polls: dict[int, int] = field(default_factory=dict)

    def api(
        self,
        _github: GitHub,
        method: str,
        path: str,
        *,
        fields: Mapping[str, str | bool] | None = None,
        paginate: bool = False,
    ) -> object:
        """Answer one call, as `GitHub._api` would.

        Returns:
            What GitHub would answer.
        """
        from canopy_review_bench.bench import BenchError  # noqa: PLC0415

        if self.fails is not None and f"{method} {path}".startswith(self.fails):
            raise BenchError(f"gh api {path} exited 1: HTTP 422")
        repo = f"repos/{REPO}"
        if method == "POST" and path == f"{repo}/pulls":
            number = len(self.opened) + 1
            self.opened[number] = dict(fields or {})
            return {"number": number}
        if method == "PATCH" and (found := re.fullmatch(rf"{repo}/pulls/(\d+)", path)):
            self.closed.append(int(found[1]))
            return {"number": int(found[1]), "state": "closed"}
        if method == "DELETE" and path.startswith(f"{repo}/git/refs/heads/"):
            self.deleted.append(path.removeprefix(f"{repo}/git/refs/heads/"))
            return None
        found = re.fullmatch(rf"{repo}/(pulls|issues)/(\d+)/(comments|reviews)\?per_page=100", path)
        assert method == "GET", f"unexpected call: {method} {path}"
        assert found is not None, f"unexpected call: {method} {path}"
        assert paginate, f"unpaged read of {path}"
        number = int(found[2])
        kind = "conversation" if found[1] == "issues" else "inline" if found[3] == "comments" else "reviews"
        # A read of the comments asks for the inline ones first, so that call starts the poll the others are part of.
        if kind == "inline":
            self._polls[number] = self._polls.get(number, 0) + 1
        poll = self._polls[number] - 1
        return [list(self.reviewer(str(self.opened[number]["title"]), poll).get(kind, ()))]


@contextmanager
def github_does(fake: FakeGitHub) -> Iterator[FakeGitHub]:
    """Answer every call the bench makes to GitHub from `fake`, for the block.

    Yields:
        The fake, to read what was done on it.
    """
    with mock.patch.object(GitHub, "_api", autospec=True, side_effect=fake.api):
        yield fake


@dataclass
class FakeClock:
    """Time that passes only when the bench sleeps."""

    at: float = 0.0
    slept: list[float] = field(default_factory=list)

    def now(self) -> float:
        """Return the time."""
        return self.at

    def sleep(self, seconds: float) -> None:
        """Pass `seconds`."""
        self.slept.append(seconds)
        self.at += seconds

    @property
    def clock(self) -> Clock:
        """It, as a run's clock."""
        return Clock(now=self.now, sleep=self.sleep)
