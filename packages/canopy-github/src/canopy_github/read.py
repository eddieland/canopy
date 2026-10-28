"""Reading PRs whole, many to a query, each page of each.

Each PR's state and labels, the checks at its head, its reviews, and its review threads with every comment.
`canopy-connect-github` prints what this reads; `canopy-post-github` reads the threads to find the one each reply
answers.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from canopy_github import (
    Client,
    GitHubError,
    Ref,
    Reply,
    ServerError,
    cut,
    error_types,
    items,
    more,
    number,
    obj,
    pages,
    refusal,
    text,
)

#: PRs one query reads: GitHub refuses a query that could return more than 500,000 nodes, and each PR asks for some
#: 5,300 (50 threads of 100 comments, and a page each of reviews, labels, and checks).
BATCH: Final = 20
#: The most labels a PR's line carries: canopy refuses a line with more, so a PR with more is not read whole.
MAX_LABELS: Final = 100
#: The longest link a `check` line carries: canopy refuses a line with a longer one.
MAX_URL: Final = 2000

_REVIEW: Final = """
fragment Review on PullRequestReview {
  id fullDatabaseId state submittedAt createdAt body url author { __typename login }
}
"""

_COMMENT: Final = """
fragment ThreadComment on PullRequestReviewComment {
  id fullDatabaseId body createdAt url author { __typename login } pullRequestReview { fullDatabaseId }
}
"""

_THREAD: Final = (
    """
fragment Thread on PullRequestReviewThread {
  id path line diffSide isOutdated isResolved
  comments(first: 100) { pageInfo { hasNextPage endCursor } nodes { ...ThreadComment } }
}
"""
    + _COMMENT
)

# Every named context, a check run or a commit status: never the combined status, which stops at 30 (DESIGN §30).
_CONTEXTS: Final = """
fragment Contexts on StatusCheckRollupContextConnection {
  pageInfo { hasNextPage endCursor }
  nodes {
    __typename
    ... on CheckRun { name status conclusion databaseId detailsUrl url }
    ... on StatusContext { context state targetUrl }
  }
}
"""

_PULL: Final = (
    """
fragment Pull on PullRequest {
  id url number title state isDraft headRefOid baseRefName mergeable mergeStateStatus
  author { login }
  labels(first: 100) { pageInfo { hasNextPage endCursor } nodes { name } }
  reviews(first: 100) { pageInfo { hasNextPage endCursor } nodes { ...Review } }
  reviewThreads(first: 50) { pageInfo { hasNextPage endCursor } nodes { ...Thread } }
  commits(last: 1) { nodes { commit { id oid statusCheckRollup { contexts(first: 100) { ...Contexts } } } } }
}
"""
    + _REVIEW
    + _THREAD
    + _CONTEXTS
)

_REVIEWS: Final = (
    """
query Reviews($id: ID!, $after: String) {
  node(id: $id) {
    ... on PullRequest { reviews(first: 100, after: $after) { pageInfo { hasNextPage endCursor } nodes { ...Review } } }
  }
}
"""
    + _REVIEW
)

_THREADS: Final = (
    """
query Threads($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 50, after: $after) { pageInfo { hasNextPage endCursor } nodes { ...Thread } }
    }
  }
}
"""
    + _THREAD
)

_THREAD_COMMENTS: Final = (
    """
query ThreadComments($id: ID!, $after: String) {
  node(id: $id) {
    ... on PullRequestReviewThread {
      comments(first: 100, after: $after) { pageInfo { hasNextPage endCursor } nodes { ...ThreadComment } }
    }
  }
}
"""
    + _COMMENT
)

_MORE_CONTEXTS: Final = (
    """
query Contexts($id: ID!, $after: String) {
  node(id: $id) { ... on Commit { statusCheckRollup { contexts(first: 100, after: $after) { ...Contexts } } } }
}
"""
    + _CONTEXTS
)

#: A commit status's state, as a check's status and conclusion: one expected is one no context has written yet.
_STATUS_STATES: Final[Mapping[str, tuple[str, str | None]]] = {
    "EXPECTED": ("pending", None),
    "PENDING": ("pending", None),
    "SUCCESS": ("completed", "success"),
    "FAILURE": ("completed", "failure"),
    "ERROR": ("completed", "error"),
}


@dataclass(frozen=True)
class Thread:
    """A review thread: its node id, where it is, and its comments' lines, oldest first."""

    id: str
    comments: tuple[Mapping[str, object], ...]


@dataclass(frozen=True)
class Pulled:
    """One PR as read: its lines, the `pr` line first, or why it was not read whole."""

    lines: Sequence[Mapping[str, object]] = ()
    error: GitHubError | None = None


def pull_requests(client: Client, refs: Sequence[Ref]) -> dict[str, Pulled]:
    """Read each of `refs`, all on `client`'s host, whole: `BATCH` to a query, then any page past each one's first.

    The lines are DESIGN §30's: ids, states, times, and bodies cut at `MAX_BODY`, never a diff or a log. A PR GitHub
    does not return, or one a later page of fails, is not read whole, and the rest still are. A query of many PRs
    GitHub answers with a server error is read again in halves rather than sent again whole, as one too heavy to answer
    in time would fail each time; a query of one PR is sent again.

    Returns:
        Each PR's read, by its URL.
    """
    found: dict[str, Pulled] = {}
    for start in range(0, len(refs), BATCH):
        chunk = refs[start : start + BATCH]
        found |= _read(client, chunk, _ask(client, chunk))
    return found


def threads(client: Client, ref: Ref) -> list[Thread]:
    """Every review thread of `ref`, each with every comment.

    Returns:
        The threads, in GitHub's order.

    Raises:
        GitHubError: GitHub refused a page, could not be reached, or has no such PR.
    """
    return list(_threads(client, ref, None))


def _ask(client: Client, refs: Sequence[Ref]) -> Reply | GitHubError:
    # A batch's halves are its new tries: sending it again whole would spend the connector's time on what may fail
    # each time.
    try:
        return client.ask(_batch(len(refs)), _variables(refs), retry=len(refs) == 1)
    except GitHubError as e:
        return e


def _read(client: Client, refs: Sequence[Ref], reply: Reply | GitHubError, *, split: bool = True) -> dict[str, Pulled]:
    """Each of `refs` from the reply to the query that read them, or, for a server error, from its halves' replies.

    Returns:
        Each PR's read, by its URL.
    """
    if split and isinstance(reply, ServerError) and len(refs) > 1:
        return _halves(client, refs)
    if isinstance(reply, GitHubError):
        return {ref.url: Pulled(error=reply) for ref in refs}
    found: dict[str, Pulled] = {}
    for alias, ref in zip(_aliases(len(refs)), refs, strict=True):
        try:
            found[ref.url] = Pulled(_pull(client, ref, _aliased(reply, alias, ref)))
        except GitHubError as e:
            found[ref.url] = Pulled(error=e)
    return found


def _halves(client: Client, refs: Sequence[Ref]) -> dict[str, Pulled]:
    """Read `refs`, whose query GitHub answered with a server error, in two halves, a half that fails split again.

    When both halves fail, GitHub is failing whatever it is asked rather than one PR too heavy for a query, and neither
    is split again: a GitHub that is down is sent three queries a batch, or more for a batch of two or three.

    Returns:
        Each PR's read, by its URL.
    """
    middle = len(refs) // 2
    halves = (refs[:middle], refs[middle:])
    replies = [_ask(client, half) for half in halves]
    split = not all(isinstance(reply, GitHubError) for reply in replies)
    found: dict[str, Pulled] = {}
    for half, reply in zip(halves, replies, strict=True):
        found |= _read(client, half, reply, split=split)
    return found


def _batch(count: int) -> str:
    """The query that reads `count` PRs, each under its alias, with its owner, name, and number as variables.

    Returns:
        The query.
    """
    params = ", ".join(f"$o{i}: String!, $n{i}: String!, $k{i}: Int!" for i in range(count))
    fields = "\n".join(
        f"  {alias}: repository(owner: $o{i}, name: $n{i}) {{ pullRequest(number: $k{i}) {{ ...Pull }} }}"
        for i, alias in enumerate(_aliases(count))
    )
    return f"query PullRequests({params}) {{\n{fields}\n}}\n{_PULL}"


def _aliases(count: int) -> list[str]:
    return [f"p{i}" for i in range(count)]


def _variables(refs: Sequence[Ref]) -> dict[str, object]:
    found: dict[str, object] = {}
    for i, ref in enumerate(refs):
        found |= {f"o{i}": ref.owner, f"n{i}": ref.name, f"k{i}": ref.number}
    return found


def _aliased(reply: Reply, alias: str, ref: Ref) -> Mapping[str, object]:
    """The PR under `alias` in a batch's reply.

    Returns:
        The PR's node.

    Raises:
        GitHubError: An error the reply carries is about it, or about no one PR, or GitHub returned no such PR.
    """
    errors = [e for e in reply.errors if _about(e, alias)]
    if errors:
        raise GitHubError(refusal(errors), certain=True, types=error_types(errors))
    repository = obj(reply.data.get(alias), f"repository {ref.owner}/{ref.name}")
    return obj(repository.get("pullRequest"), f"pull request {ref.url}")


def _about(error: Mapping[str, object], alias: str) -> bool:
    # An error with no path is about the whole query, so about every PR in it.
    path = error.get("path")
    return not isinstance(path, list) or not path or path[0] == alias


def _pull(client: Client, ref: Ref, pr: Mapping[str, object]) -> list[Mapping[str, object]]:
    """Read the rest of one PR from its first page: its `pr` line, its checks, its reviews, and its review comments.

    Returns:
        The lines, the `pr` line first.

    Raises:
        GitHubError: A later page could not be read, or the PR has more labels than its line may carry.
    """
    labels = obj(pr.get("labels"), "labels")
    if obj(labels.get("pageInfo"), "pageInfo").get("hasNextPage") is True:
        raise GitHubError(f"it has more than {MAX_LABELS} labels", certain=True)
    node = text(pr.get("id")) or ""

    def reviews_after(after: str) -> Mapping[str, object]:
        found = obj(client.query(_REVIEWS, {"id": node, "after": after}).get("node"), "pull request")
        return obj(found.get("reviews"), "reviews")

    lines: list[Mapping[str, object]] = [_pr_line(ref, pr, items(labels.get("nodes")))]
    lines.extend(_checks(client, ref, pr))
    lines.extend(_review(ref, review) for review in more(obj(pr.get("reviews"), "reviews"), reviews_after))
    first = obj(pr.get("reviewThreads"), "reviewThreads")
    lines.extend(comment for thread in _threads(client, ref, first) for comment in thread.comments)
    return lines


def _threads(client: Client, ref: Ref, first: Mapping[str, object] | None) -> Iterator[Thread]:
    """Each review thread of `ref`, from its first page when in hand, each with every comment.

    Yields:
        Each thread, in GitHub's order.
    """

    def fetch(after: str | None) -> Mapping[str, object]:
        if after is None and first is not None:
            return first
        variables = {"owner": ref.owner, "name": ref.name, "number": ref.number, "after": after}
        repository = obj(client.query(_THREADS, variables).get("repository"), f"repository {ref.owner}/{ref.name}")
        pr = obj(repository.get("pullRequest"), f"pull request {ref.url}")
        return obj(pr.get("reviewThreads"), "reviewThreads")

    for node in pages(fetch):
        yield _thread(client, ref, node)


def _pr_line(ref: Ref, pr: Mapping[str, object], labels: Sequence[Mapping[str, object]]) -> Mapping[str, object]:
    state = text(pr.get("state"))
    mergeable = text(pr.get("mergeable"))
    merge_state = text(pr.get("mergeStateStatus"))
    return {
        "kind": "pr",
        "url": ref.url,
        "node": text(pr.get("id")),
        "repository": f"{ref.owner}/{ref.name}",
        "number": ref.number,
        "head_sha": text(pr.get("headRefOid")),
        "base_ref": text(pr.get("baseRefName")),
        "state": state.lower() if state else None,
        "draft": pr.get("isDraft") is True,
        "mergeable": mergeable.lower() if mergeable else None,
        "mergeable_state": merge_state.lower() if merge_state else None,
        "author": _login(pr.get("author")),
        # The author's text, which canopy cuts and marks; for display only.
        "title": text(pr.get("title")),
        "labels": [name for label in labels if (name := text(label.get("name"))) is not None],
    }


def _checks(client: Client, ref: Ref, pr: Mapping[str, object]) -> list[Mapping[str, object]]:
    """A `check` line for each context at the PR's head, every page of them; one per name, the newest run of it.

    A name can come back more than once, as when a workflow ran for two events; canopy keeps one row a name, so the
    line is the check run GitHub made last, which is the one its page shows.

    Returns:
        The lines, in GitHub's order.
    """
    commits = items(obj(pr.get("commits"), "commits").get("nodes"))
    commit: Mapping[str, object] = obj(commits[-1].get("commit"), "commit") if commits else {}
    sha = text(commit.get("oid"))
    rollup = commit.get("statusCheckRollup")
    if sha is None or not isinstance(rollup, dict):
        # Nothing has written a check or a status at the head yet.
        return []
    first = obj(obj(rollup, "statusCheckRollup").get("contexts"), "contexts")
    commit_id = text(commit.get("id")) or ""

    def after(cursor: str) -> Mapping[str, object]:
        found = obj(client.query(_MORE_CONTEXTS, {"id": commit_id, "after": cursor}).get("node"), "commit")
        return obj(obj(found.get("statusCheckRollup"), "statusCheckRollup").get("contexts"), "contexts")

    newest: dict[str, tuple[int, Mapping[str, object]]] = {}
    for node in more(first, after):
        found = _context(ref, sha, node)
        if found is None:
            continue
        rank, line = found
        name = str(line["name"])
        if name not in newest or rank >= newest[name][0]:
            newest[name] = (rank, line)
    return [line for _, line in newest.values()]


def _context(ref: Ref, sha: str, node: Mapping[str, object]) -> tuple[int, Mapping[str, object]] | None:
    """A context's `check` line, and its rank among contexts of its name: a check run's id, a status's 0.

    Returns:
        The rank and the line, or None for a context with no name.
    """
    line: dict[str, object] = {"kind": "check", "pr": ref.url, "head_sha": sha}
    if node.get("__typename") == "StatusContext":
        name, state = text(node.get("context")), text(node.get("state")) or ""
        status, conclusion = _STATUS_STATES.get(state, (state.lower(), None))
        line |= {"name": name, "status": status, "conclusion": conclusion, "run_id": None}
        line["url"] = _url(node.get("targetUrl"))
        rank = 0
    else:
        name, status, conclusion = text(node.get("name")), text(node.get("status")), text(node.get("conclusion"))
        run_id = number(node.get("databaseId"))
        line |= {
            "name": name,
            "status": status.lower() if status else None,
            "conclusion": conclusion.lower() if conclusion else None,
            "run_id": run_id,
            "url": _url(node.get("detailsUrl")) or _url(node.get("url")),
        }
        rank = run_id or 0
    return None if name is None else (rank, line)


def _url(value: object) -> str | None:
    # A context's link is whatever its writer set; one canopy would refuse is left out rather than refuse the PR.
    found = text(value)
    if found is None or not found.startswith("https://") or len(found) > MAX_URL or any(c.isspace() for c in found):
        return None
    return found


def _review(ref: Ref, node: Mapping[str, object]) -> Mapping[str, object]:
    state = text(node.get("state"))
    return {
        "kind": "review",
        "item": "review",
        "pr": ref.url,
        "id": number(node.get("fullDatabaseId")),
        "node": text(node.get("id")),
        "author": _login(node.get("author")),
        "bot": _bot(node.get("author")),
        "state": state.lower() if state else None,
        # A pending review has not been submitted.
        "time": text(node.get("submittedAt")) or text(node.get("createdAt")),
        "body": cut(node.get("body")),
        "url": text(node.get("url")),
    }


def _thread(client: Client, ref: Ref, node: Mapping[str, object]) -> Thread:
    thread_id = text(node.get("id")) or ""
    side = text(node.get("diffSide"))
    where: Mapping[str, object] = {
        "id": thread_id,
        "path": text(node.get("path")),
        "line": number(node.get("line")),
        "side": side.lower() if side else None,
        "outdated": node.get("isOutdated") is True,
        "resolved": node.get("isResolved") is True,
    }

    def after(cursor: str) -> Mapping[str, object]:
        found = obj(client.query(_THREAD_COMMENTS, {"id": thread_id, "after": cursor}).get("node"), "thread")
        return obj(found.get("comments"), "comments")

    comments = tuple(_comment(ref, where, comment) for comment in more(obj(node.get("comments"), "comments"), after))
    return Thread(id=thread_id, comments=comments)


def _comment(ref: Ref, where: Mapping[str, object], node: Mapping[str, object]) -> Mapping[str, object]:
    review = node.get("pullRequestReview")
    return {
        "kind": "review",
        "item": "comment",
        "pr": ref.url,
        "id": number(node.get("fullDatabaseId")),
        "node": text(node.get("id")),
        "author": _login(node.get("author")),
        "bot": _bot(node.get("author")),
        "time": text(node.get("createdAt")),
        "body": cut(node.get("body")),
        "url": text(node.get("url")),
        "review": number(obj(review, "review").get("fullDatabaseId")) if isinstance(review, dict) else None,
        "thread": dict(where),
    }


def _login(author: object) -> str | None:
    # A deleted account's content has no author.
    return text(obj(author, "author").get("login")) if isinstance(author, dict) else None


def _bot(author: object) -> bool:
    return isinstance(author, dict) and obj(author, "author").get("__typename") == "Bot"
