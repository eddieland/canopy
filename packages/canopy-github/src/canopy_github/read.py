"""Reading one PR whole: its state, its reviews, and its review threads with every comment, each page of each.

`canopy-connect-github` prints what this reads; `canopy-post-github` reads the threads to find the one each reply
answers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from canopy_github import Client, Ref, cut, number, obj, pages, text

_PULL_REQUEST = """
query PullRequest($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      id url number state isDraft headRefOid baseRefName mergeable
      author { login }
      reviews(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes { id fullDatabaseId state submittedAt createdAt body url author { __typename login } }
      }
    }
  }
}
"""

_THREADS = """
query Threads($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 50, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id path line diffSide isOutdated isResolved
          comments(first: 100) { pageInfo { hasNextPage endCursor } nodes { ...ThreadComment } }
        }
      }
    }
  }
}
fragment ThreadComment on PullRequestReviewComment {
  id fullDatabaseId body createdAt url author { __typename login } pullRequestReview { fullDatabaseId }
}
"""

_THREAD_COMMENTS = """
query ThreadComments($id: ID!, $after: String) {
  node(id: $id) {
    ... on PullRequestReviewThread {
      comments(first: 100, after: $after) { pageInfo { hasNextPage endCursor } nodes { ...ThreadComment } }
    }
  }
}
fragment ThreadComment on PullRequestReviewComment {
  id fullDatabaseId body createdAt url author { __typename login } pullRequestReview { fullDatabaseId }
}
"""


@dataclass(frozen=True)
class Thread:
    """A review thread: its node id, where it is, and its comments' lines, oldest first."""

    id: str
    comments: tuple[Mapping[str, object], ...]


def pull_request(client: Client, ref: Ref) -> list[Mapping[str, object]]:
    """Read `ref` whole: its `pr` line, a `review` line for each review, and one for each review comment.

    The lines are ROADMAP M36's: ids, states, times, and bodies cut at `MAX_BODY`, never a diff.

    Returns:
        The lines, the `pr` line first.

    Raises:
        GitHubError: GitHub refused a page, could not be reached, or has no such PR.
    """
    first: dict[str, object] = {}

    def fetch(after: str | None) -> Mapping[str, object]:
        pr = _pr(client, _PULL_REQUEST, ref, after)
        first.setdefault("pr", pr)
        return obj(pr.get("reviews"), "reviews")

    reviews = [_review(ref, node) for node in pages(fetch)]
    pr = obj(first["pr"], "pullRequest")
    lines: list[Mapping[str, object]] = [_pr_line(ref, pr), *reviews]
    lines.extend(comment for thread in threads(client, ref) for comment in thread.comments)
    return lines


def threads(client: Client, ref: Ref) -> list[Thread]:
    """Every review thread of `ref`, each with every comment.

    Returns:
        The threads, in GitHub's order.

    Raises:
        GitHubError: GitHub refused a page, could not be reached, or has no such PR.
    """

    def fetch(after: str | None) -> Mapping[str, object]:
        return obj(_pr(client, _THREADS, ref, after).get("reviewThreads"), "reviewThreads")

    return [_thread(client, ref, node) for node in pages(fetch)]


def _pr(client: Client, document: str, ref: Ref, after: str | None) -> Mapping[str, object]:
    variables = {"owner": ref.owner, "name": ref.name, "number": ref.number, "after": after}
    repository = obj(client.query(document, variables).get("repository"), f"repository {ref.owner}/{ref.name}")
    return obj(repository.get("pullRequest"), f"pull request {ref.url}")


def _pr_line(ref: Ref, pr: Mapping[str, object]) -> Mapping[str, object]:
    state = text(pr.get("state"))
    mergeable = text(pr.get("mergeable"))
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
        "author": _login(pr.get("author")),
    }


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
    first = obj(node.get("comments"), "comments")

    def fetch(after: str | None) -> Mapping[str, object]:
        if after is None:
            return first
        found = obj(client.query(_THREAD_COMMENTS, {"id": thread_id, "after": after}).get("node"), "thread")
        return obj(found.get("comments"), "comments")

    comments = tuple(_comment(ref, where, comment) for comment in pages(fetch))
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
