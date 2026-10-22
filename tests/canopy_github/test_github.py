"""canopy's GitHub programs (DESIGN §29), against a local stand-in for GitHub's GraphQL API."""

import contextlib
import json
import os
import re
import threading
from collections.abc import Callable, Generator, Mapping, Sequence
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar, override
from unittest import mock

import canopy_github
import click
import pytest
from canopy_github import Hosts, connect, post
from canopy_github import read as read_module
from canopy_github import repository as repository_module

from canopy.core import config, observe, records, sql
from canopy.core.vocab import CheckStatus, ConnectorRunStatus, MergeState
from canopy.infra import logs, procs
from tests.conftest import CanopyEnv, executable, invoke

PR = "https://github.com/acme/api/pull/7"
HEAD = "9b2f4c6e1a7d"
PAGE = 2


@dataclass
class Comment:
    id: int
    body: str
    author: str = "alice"
    bot: bool = False
    review: int | None = None
    at: str = "2026-10-18T10:00:00Z"
    reactions: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Thread:
    id: str
    path: str
    line: int | None
    comments: list[Comment]
    side: str = "RIGHT"
    outdated: bool = False
    resolved: bool = False


@dataclass
class Review:
    node: str
    id: int
    author: str
    state: str
    body: str = ""
    at: str | None = "2026-10-18T10:00:00Z"
    commit: str | None = None


@dataclass
class Pull:
    node: str
    reviews: list[Review] = field(default_factory=list)
    threads: list[Thread] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    # Each context at the head as GitHub's rollup lists it, a CheckRun's or a StatusContext's fields; None for a head
    # nothing has written a check or a status on.
    contexts: list[dict[str, Any]] | None = None
    state: str = "OPEN"
    merge_state: str = "CLEAN"


def run(name: str, status: str = "COMPLETED", conclusion: str | None = "SUCCESS", id_: int = 1) -> dict[str, Any]:
    """A check run as the rollup lists it."""
    url = f"https://github.com/acme/api/actions/runs/{id_}/job/{id_}"
    return {
        "__typename": "CheckRun",
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "databaseId": id_,
        "detailsUrl": url,
        "url": f"https://github.com/acme/api/runs/{id_}",
    }


def status(context: str, state: str, url: str | None = "https://ci.example.com/build/1") -> dict[str, Any]:
    """A commit status as the rollup lists it."""
    return {"__typename": "StatusContext", "context": context, "state": state, "targetUrl": url}


@dataclass
class Fake:
    """GitHub's state, and what each operation should do.

    `fail` maps an operation to `refuse`, `500`, or `lost`: carried out, but answered with a 502.
    """

    pulls: dict[tuple[str, str, int], Pull] = field(default_factory=dict)
    # Each repository's branches, by owner and name: a branch's name to its head's sha.
    branches: dict[tuple[str, str], dict[str, str]] = field(default_factory=dict)
    # What a search returns, by its query: PRs' and issues' URLs; and the count it reports, when not their number.
    searches: dict[str, list[str]] = field(default_factory=dict)
    search_count: int | None = None
    issues: dict[tuple[str, str, int], str] = field(default_factory=dict)
    issue_comments: list[tuple[str, str]] = field(default_factory=list)
    # The login the token is for; empty for a reply that has none.
    viewer: str = "me"
    fail: dict[str, str] = field(default_factory=dict)
    seen: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    next_id: int = 9000

    def ops(self) -> list[str]:
        return [op for op, _, _ in self.seen]

    def new_id(self) -> int:
        self.next_id += 1
        return self.next_id

    def pull_by_node(self, node: str) -> Pull:
        return next(p for p in self.pulls.values() if p.node == node)

    def review_by_node(self, node: str) -> tuple[Pull, Review] | None:
        for pull in self.pulls.values():
            for review in pull.reviews:
                if review.node == node:
                    return pull, review
        return None

    def handle(self, document: str, variables: dict[str, Any]) -> Mapping[str, Any]:  # noqa: C901, PLR0911, PLR0912, PLR0915
        match = re.match(r"\s*(?:query|mutation)\s+(\w+)", document)
        assert match, document
        op = match.group(1)
        if op == "PullRequests":
            return self.pull_requests(variables)
        if op in {"Threads", "PullRequestId"}:
            pull = self.pulls.get((variables["owner"], variables["name"], variables["number"]))
            if pull is None:
                return {"data": {"repository": {"pullRequest": None}}, "errors": [{"message": "not found"}]}
            if op == "PullRequestId":
                return {"data": {"repository": {"pullRequest": {"id": pull.node}}}}
            threads = page([self.thread_node(t) for t in pull.threads], variables["after"])
            return {"data": {"repository": {"pullRequest": {"reviewThreads": threads}}}}
        if op == "Reviews":
            pull = self.pull_by_node(variables["id"])
            return {"data": {"node": {"reviews": page(self.review_nodes(pull), variables["after"])}}}
        if op == "Contexts":
            pull = self.pull_by_node(variables["id"].removeprefix("C_"))
            contexts = page(pull.contexts or [], variables["after"])
            return {"data": {"node": {"statusCheckRollup": {"contexts": contexts}}}}
        if op == "Branches":
            found = self.branches.get((variables["owner"], variables["name"]))
            if found is None:
                return {"data": {"repository": None}, "errors": [{"type": "NOT_FOUND", "message": "no repository"}]}
            # GitHub matches a ref's name against the query more loosely than a prefix.
            nodes = [{"name": n, "target": {"oid": sha}} for n, sha in found.items() if variables["prefix"] in n]
            return {"data": {"repository": {"refs": page(nodes, variables["after"])}}}
        if op == "Search":
            urls = self.searches.get(variables["query"], [])
            nodes = [{"url": u} if "/pull/" in u else {} for u in urls]
            count = len(urls) if self.search_count is None else self.search_count
            return {"data": {"search": {"issueCount": count, **page(nodes, variables["after"])}}}
        if op == "ThreadComments":
            thread = next(t for p in self.pulls.values() for t in p.threads if t.id == variables["id"])
            comments = page([self.comment_node(c) for c in thread.comments], variables["after"])
            return {"data": {"node": {"comments": comments}}}
        if op == "Viewer":
            return {"data": {"viewer": {"login": self.viewer or None}}}
        if op == "PendingReviews":
            pull = self.pulls[variables["owner"], variables["name"], variables["number"]]
            # GitHub shows a pending review to its author alone.
            nodes = [
                {"id": r.node, "author": {"login": r.author}}
                for r in pull.reviews
                if r.state == "PENDING" and r.author == self.viewer
            ]
            return {"data": {"repository": {"pullRequest": {"reviews": {"nodes": nodes}}}}}
        if op == "IssueId":
            node = self.issues.get((variables["owner"], variables["name"], variables["number"]))
            return {"data": {"repository": {"issue": None if node is None else {"id": node}}}}
        if op == "Review":
            found = self.review_by_node(variables["id"])
            if found is None:
                return {"data": {"node": None}, "errors": [{"type": "NOT_FOUND", "message": "no node"}]}
            pull, review = found
            node = {"state": review.state, "author": {"login": review.author}, "pullRequest": {"id": pull.node}}
            return {"data": {"node": node}}
        if op == "AddReview":
            pull = self.pull_by_node(variables["pr"])
            if any(r.author == self.viewer and r.state == "PENDING" for r in pull.reviews):
                return {"errors": [{"message": "User can only have one pending review per pull request"}]}
            review = Review(
                node=f"PRR_{self.new_id()}",
                id=self.next_id,
                author=self.viewer,
                state="PENDING",
                body=variables.get("body") or "",
                at=None,
                commit=variables.get("commit"),
            )
            pull.reviews.append(review)
            node = {"id": review.node, "fullDatabaseId": str(review.id)}
            return {"data": {"addPullRequestReview": {"pullRequestReview": node}}}
        if op == "Reply":
            found = self.review_by_node(variables["review"])
            assert found is not None
            _, review = found
            thread = next(t for p in self.pulls.values() for t in p.threads if t.id == variables["thread"])
            comment = Comment(id=self.new_id(), body=variables["body"], author=self.viewer, review=review.id)
            thread.comments.append(comment)
            node = {"fullDatabaseId": str(comment.id), "url": f"{PR}#discussion_r{comment.id}"}
            return {"data": {"addPullRequestReviewThreadReply": {"comment": node}}}
        if op == "Thread":
            found = self.review_by_node(variables["review"])
            assert found is not None
            pull, review = found
            comment = Comment(id=self.new_id(), body=variables["body"], author=self.viewer, review=review.id)
            pull.threads.append(Thread(f"PRRT_{comment.id}", variables["path"], variables["line"], [comment]))
            node = {"fullDatabaseId": str(comment.id), "url": f"{PR}#discussion_r{comment.id}"}
            return {"data": {"addPullRequestReviewThread": {"thread": {"comments": {"nodes": [node]}}}}}
        if op == "Submit":
            assert "event: COMMENT" in document
            found = self.review_by_node(variables["review"])
            assert found is not None
            _, review = found
            review.state, review.body, review.at = "COMMENTED", variables["body"] or "", "2026-10-18T11:00:00Z"
            node = {
                "fullDatabaseId": str(review.id),
                "url": f"{PR}#pullrequestreview-{review.id}",
                "state": "COMMENTED",
            }
            return {"data": {"submitPullRequestReview": {"pullRequestReview": node}}}
        if op == "Delete":
            found = self.review_by_node(variables["review"])
            assert found is not None
            pull, review = found
            pull.reviews.remove(review)
            for thread in pull.threads:
                thread.comments = [c for c in thread.comments if c.review != review.id]
            return {"data": {"deletePullRequestReview": {"clientMutationId": None}}}
        if op == "React":
            comment = next(
                c
                for p in self.pulls.values()
                for t in p.threads
                for c in t.comments
                if f"PRRC_{c.id}" == variables["subject"]
            )
            # GitHub keeps one reaction of a kind a person, however often it is asked.
            if (self.viewer, variables["content"]) not in comment.reactions:
                comment.reactions.append((self.viewer, variables["content"]))
            return {"data": {"addReaction": {"reaction": {"content": variables["content"]}}}}
        if op == "Comment":
            self.issue_comments.append((variables["subject"], variables["body"]))
            node = {
                "fullDatabaseId": str(self.new_id()),
                "url": f"https://github.com/acme/api/issues/12#c{self.next_id}",
            }
            return {"data": {"addComment": {"commentEdge": {"node": node}}}}
        raise AssertionError(f"unexpected operation {op}")

    def pull_requests(self, variables: dict[str, Any]) -> Mapping[str, Any]:
        """A batch: each PR under its alias, `p0` and on, with its owner, name, and number in `o0`, `n0`, `k0`."""
        data: dict[str, Any] = {}
        errors: list[dict[str, Any]] = []
        i = 0
        while f"o{i}" in variables:
            pull = self.pulls.get((variables[f"o{i}"], variables[f"n{i}"], variables[f"k{i}"]))
            data[f"p{i}"] = {"pullRequest": None if pull is None else self.pr_node(pull)}
            if pull is None:
                errors.append({"type": "NOT_FOUND", "path": [f"p{i}", "pullRequest"], "message": "no such PR"})
            i += 1
        return {"data": data, **({"errors": errors} if errors else {})}

    def pr_node(self, pull: Pull) -> dict[str, Any]:
        rollup = None if pull.contexts is None else {"contexts": page(pull.contexts, None)}
        labels = [{"name": name} for name in pull.labels]
        return {
            "id": pull.node,
            "url": PR,
            "number": 7,
            "state": pull.state,
            "isDraft": False,
            "headRefOid": HEAD,
            "baseRefName": "main",
            "mergeable": "MERGEABLE",
            "mergeStateStatus": pull.merge_state,
            "author": {"login": "me"},
            # A page of labels holds 100, as the reader asks, so a PR with more has another page.
            "labels": {"nodes": labels[:100], "pageInfo": {"hasNextPage": len(labels) > 100, "endCursor": "100"}},
            "reviews": page(self.review_nodes(pull), None),
            "reviewThreads": page([self.thread_node(t) for t in pull.threads], None),
            "commits": {"nodes": [{"commit": {"id": f"C_{pull.node}", "oid": HEAD, "statusCheckRollup": rollup}}]},
        }

    def review_nodes(self, pull: Pull) -> list[dict[str, Any]]:
        return [
            {
                "id": r.node,
                "fullDatabaseId": str(r.id),
                "state": r.state,
                "submittedAt": r.at if r.state != "PENDING" else None,
                "createdAt": "2026-10-18T09:00:00Z",
                "body": r.body,
                "url": f"{PR}#pullrequestreview-{r.id}",
                "author": {"__typename": "User", "login": r.author},
            }
            for r in pull.reviews
        ]

    def thread_node(self, thread: Thread) -> dict[str, Any]:
        return {
            "id": thread.id,
            "path": thread.path,
            "line": thread.line,
            "diffSide": thread.side,
            "isOutdated": thread.outdated,
            "isResolved": thread.resolved,
            "comments": page([self.comment_node(c) for c in thread.comments], None),
        }

    def comment_node(self, comment: Comment) -> dict[str, Any]:
        return {
            "id": f"PRRC_{comment.id}",
            "fullDatabaseId": str(comment.id),
            "body": comment.body,
            "createdAt": comment.at,
            "url": f"{PR}#discussion_r{comment.id}",
            "author": {"__typename": "Bot" if comment.bot else "User", "login": comment.author},
            "pullRequestReview": None if comment.review is None else {"fullDatabaseId": str(comment.review)},
        }


def page(nodes: list[dict[str, Any]], after: str | None) -> dict[str, Any]:
    start = 0 if after is None else int(after)
    end = start + PAGE
    return {"nodes": nodes[start:end], "pageInfo": {"hasNextPage": end < len(nodes), "endCursor": str(end)}}


class _Api(BaseHTTPRequestHandler):
    fake: ClassVar[Fake]

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(length))
        op = re.match(r"\s*(?:query|mutation)\s+(\w+)", request["query"])
        assert op
        _Api.fake.seen.append((op.group(1), self.headers["Authorization"], request["variables"]))
        if _Api.fake.fail.get(op.group(1)) == "lost":
            _Api.fake.handle(request["query"], request["variables"])
        if _Api.fake.fail.get(op.group(1)) in {"500", "lost"}:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(b"bad gateway")
            return
        if _Api.fake.fail.get(op.group(1)) == "refuse":
            reply: Mapping[str, Any] = {"errors": [{"message": f"{op.group(1)} refused"}]}
        else:
            reply = _Api.fake.handle(request["query"], request["variables"])
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(reply).encode())

    @override
    def log_message(self, format: str, *args: Any) -> None:
        del format, args


class _Redirect(BaseHTTPRequestHandler):
    to: ClassVar[str]

    def do_POST(self) -> None:
        self.send_response(302)
        self.send_header("Location", _Redirect.to)
        self.end_headers()

    @override
    def log_message(self, format: str, *args: Any) -> None:
        del format, args


class _Listener(BaseHTTPRequestHandler):
    heard: ClassVar[list[str | None]] = []

    def do_GET(self) -> None:
        _Listener.heard.append(self.headers["Authorization"])
        self.send_response(200)
        self.end_headers()

    def do_POST(self) -> None:
        self.do_GET()

    @override
    def log_message(self, format: str, *args: Any) -> None:
        del format, args


@contextlib.contextmanager
def serving(handler: type[BaseHTTPRequestHandler]) -> Generator[str]:
    """Serve `handler` on a local port until the block ends. Yields its URL."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/graphql"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def github() -> Generator[tuple[Fake, str]]:
    """A stand-in for GitHub's GraphQL API, holding one PR with a review and two threads. Yields it and its URL."""
    fake = Fake()
    fake.pulls["acme", "api", 7] = Pull(
        node="PR_7",
        reviews=[Review(node="PRR_1", id=101, author="alice", state="COMMENTED", body="A few things.")],
        threads=[
            Thread(
                id="PRRT_1",
                path="src/app.py",
                line=12,
                comments=[Comment(id=501, body="Rename this.", review=101)],
            ),
            Thread(
                id="PRRT_2",
                path="src/db.py",
                line=None,
                outdated=True,
                comments=[Comment(id=502, body="Why?", review=101), Comment(id=503, body="Because.", author="me")],
            ),
        ],
    )
    fake.issues["acme", "api", 12] = "I_12"
    _Api.fake = fake
    with serving(_Api) as url:
        yield fake, url


def read(
    url: str,
    request: object,
    hosts: list[str] | None = None,
    *,
    token_of: Callable[[str], str] = lambda _: "t",
) -> tuple[int, list[dict[str, Any]], str]:

    def endpoint_of(host: str) -> str:
        if hosts is not None:
            hosts.append(host)
        return url

    result = invoke(connect.main, stdin=json.dumps(request), obj=Hosts(endpoint_of, token_of))
    return result.exit_code, [json.loads(line) for line in result.stdout.splitlines()], result.stderr


def send(url: str, request: object) -> tuple[int, list[dict[str, Any]], str]:
    result = invoke(post.main, stdin=json.dumps(request), obj=Hosts(lambda _: url, lambda _: "t"))
    return result.exit_code, [json.loads(line) for line in result.stdout.splitlines()], result.stderr


# Reading


def test_the_reader_prints_a_prs_reviews_and_threads_then_its_end(github: tuple[Fake, str]) -> None:
    _, url = github
    code, lines, _ = read(url, {"prs": [PR]})
    assert code == 0
    assert [(line["kind"], line.get("item"), line.get("id")) for line in lines] == [
        ("pr", None, None),
        ("review", "review", 101),
        ("review", "comment", 501),
        ("review", "comment", 502),
        ("review", "comment", 503),
        ("end", None, None),
    ]
    pr, review, first, *_, end = lines
    assert pr == {
        "kind": "pr",
        "url": PR,
        "node": "PR_7",
        "repository": "acme/api",
        "number": 7,
        "head_sha": "9b2f4c6e1a7d",
        "base_ref": "main",
        "state": "open",
        "draft": False,
        "mergeable": "mergeable",
        "mergeable_state": "clean",
        "author": "me",
        "labels": [],
    }
    assert review["state"] == "commented"
    assert review["body"] == "A few things."
    assert first["thread"] == {
        "id": "PRRT_1",
        "path": "src/app.py",
        "line": 12,
        "side": "right",
        "outdated": False,
        "resolved": False,
    }
    assert first["review"] == 101
    assert first["author"] == "alice"
    assert lines[3]["thread"]["outdated"] is True
    assert lines[3]["thread"]["line"] is None
    assert end == {"kind": "end", "prs": [PR]}


def test_the_reader_reads_every_page(github: tuple[Fake, str]) -> None:
    fake, url = github
    pull = fake.pulls["acme", "api", 7]
    pull.reviews += [Review(node=f"PRR_{n}", id=n, author="bob", state="APPROVED") for n in (102, 103)]
    pull.threads.append(
        Thread(id="PRRT_3", path="a.py", line=1, comments=[Comment(id=n, body="x") for n in (601, 602, 603)]),
    )
    pull.contexts = [run(f"job-{n}", id_=n) for n in range(1, 6)]
    _, lines, _ = read(url, {"prs": [PR]})
    ids = [line["id"] for line in lines if line["kind"] == "review"]
    assert ids == [101, 102, 103, 501, 502, 503, 601, 602, 603]
    assert [line["name"] for line in lines if line["kind"] == "check"] == [f"job-{n}" for n in range(1, 6)]
    assert {"Reviews", "Threads", "ThreadComments", "Contexts"} <= set(fake.ops())


def test_a_prs_line_carries_its_labels_and_mergeable_state(github: tuple[Fake, str]) -> None:
    fake, url = github
    pull = fake.pulls["acme", "api", 7]
    pull.labels, pull.merge_state, pull.state = ["agent", "needs-human"], "BEHIND", "MERGED"
    _, [pr, *_], _ = read(url, {"prs": [PR]})
    assert (pr["labels"], pr["mergeable_state"], pr["state"]) == (["agent", "needs-human"], "behind", "merged")


def test_a_pr_with_more_labels_than_its_line_carries_is_not_read_whole(github: tuple[Fake, str]) -> None:
    fake, url = github
    fake.pulls["acme", "api", 7].labels = [f"l{n}" for n in range(101)]
    code, lines, err = read(url, {"prs": [PR]})
    assert (code, lines) == (1, [{"kind": "end", "prs": []}])
    assert "more than 100 labels" in err


def test_each_context_at_the_head_is_a_check_whatever_wrote_it(github: tuple[Fake, str]) -> None:
    fake, url = github
    fake.pulls["acme", "api", 7].contexts = [
        run("build", id_=11),
        run("lint", status="IN_PROGRESS", conclusion=None, id_=12),
        status("deploy/approval", "PENDING"),
        status("ci/legacy", "ERROR", url="http://ci.example.com/1"),
        status("ci/new", "EXPECTED", url=None),
    ]
    _, lines, _ = read(url, {"prs": [PR]})
    checks = [line for line in lines if line["kind"] == "check"]
    assert [{k: v for k, v in c.items() if k not in {"kind", "pr", "head_sha"}} for c in checks] == [
        {
            "name": "build",
            "status": "completed",
            "conclusion": "success",
            "run_id": 11,
            "url": "https://github.com/acme/api/actions/runs/11/job/11",
        },
        {
            "name": "lint",
            "status": "in_progress",
            "conclusion": None,
            "run_id": 12,
            "url": "https://github.com/acme/api/actions/runs/12/job/12",
        },
        {
            "name": "deploy/approval",
            "status": "pending",
            "conclusion": None,
            "run_id": None,
            "url": "https://ci.example.com/build/1",
        },
        # A link canopy would refuse is left out, so the PR is still read whole.
        {"name": "ci/legacy", "status": "completed", "conclusion": "error", "run_id": None, "url": None},
        {"name": "ci/new", "status": "pending", "conclusion": None, "run_id": None, "url": None},
    ]
    assert {(c["pr"], c["head_sha"]) for c in checks} == {(PR, HEAD)}


def test_a_check_named_twice_is_its_newest_run(github: tuple[Fake, str]) -> None:
    fake, url = github
    fake.pulls["acme", "api", 7].contexts = [
        run("build", conclusion="SUCCESS", id_=9),
        run("build", conclusion="FAILURE", id_=5),
        run("test", id_=3),
    ]
    _, lines, _ = read(url, {"prs": [PR]})
    checks = [(line["name"], line["conclusion"], line["run_id"]) for line in lines if line["kind"] == "check"]
    assert checks == [("build", "success", 9), ("test", "success", 3)]


def test_the_prs_are_read_many_to_a_query(github: tuple[Fake, str]) -> None:
    fake, url = github
    others = [f"https://github.com/acme/api/pull/{n}" for n in (8, 9)]
    for n in (8, 9):
        fake.pulls["acme", "api", n] = Pull(node=f"PR_{n}")
    _, lines, _ = read(url, {"prs": [PR, *others]})
    assert lines[-1]["prs"] == [PR, *others]
    assert fake.ops().count("PullRequests") == 1
    fake.seen.clear()
    with mock.patch.object(read_module, "BATCH", 2):
        _, lines, _ = read(url, {"prs": [PR, *others]})
    assert lines[-1]["prs"] == [PR, *others]
    assert fake.ops().count("PullRequests") == 2


def test_a_pr_not_read_whole_prints_nothing_and_is_left_off_the_end(github: tuple[Fake, str]) -> None:
    fake, url = github
    missing = "https://github.com/acme/api/pull/8"
    code, lines, err = read(url, {"prs": [missing, PR]})
    assert code == 1
    assert lines[0]["kind"] == "pr"
    assert all(line.get("pr", line.get("url")) != missing for line in lines[:-1])
    assert lines[-1] == {"kind": "end", "prs": [PR]}
    assert f"cannot read {missing}: GitHub refused it: no such PR" in err
    assert fake.ops().count("PullRequests") == 1, "the PR it read came in the same query"


def test_a_query_github_refuses_whole_reads_none_of_its_prs(github: tuple[Fake, str]) -> None:
    fake, url = github
    fake.fail["PullRequests"] = "500"
    code, lines, err = read(url, {"prs": [PR]})
    assert (code, lines) == (1, [{"kind": "end", "prs": []}])
    assert "HTTP 502" in err


def test_the_reader_asks_each_prs_own_host(github: tuple[Fake, str]) -> None:
    fake, url = github
    fake.pulls["acme", "web", 3] = Pull(node="PR_3")
    hosts: list[str] = []
    code, lines, _ = read(url, {"prs": [PR, "https://ghe.example.com/acme/web/pull/3", PR]}, hosts)
    assert code == 0
    assert hosts == ["ghe.example.com", "github.com"]
    assert lines[-1]["prs"] == [PR, "https://ghe.example.com/acme/web/pull/3"]


def test_a_host_gh_holds_no_token_for_leaves_its_subjects_unread_and_reads_the_rest(github: tuple[Fake, str]) -> None:
    fake, url = github
    fake.branches["acme", "web"] = {"agent/PROJ-2": "c0ffee1"}

    def token_of(host: str) -> str:
        if host == "ghe.example.com":
            raise canopy_github.InputError("gh is not logged in to ghe.example.com")
        return "t"

    request = {
        "prs": ["https://ghe.example.com/acme/web/pull/3", PR],
        "repositories": [{"name": "web", "url": "https://ghe.example.com/acme/web.git"}],
        "branch_prefix": "agent/",
    }
    code, lines, err = read(url, request, token_of=token_of)
    assert code == 1
    assert lines[-1] == {"kind": "end", "prs": [PR], "repositories": []}
    assert "cannot read repository web: gh is not logged in to ghe.example.com" in err


# Branches


def test_each_repository_prints_its_branches_under_the_prefix(github: tuple[Fake, str]) -> None:
    fake, url = github
    fake.branches["acme", "api"] = {
        "main": "aaaaaaa",
        "agent/PROJ-1-fix": "bbbbbbb",
        "agent/PROJ-2": "ccccccc",
        "old-agent/PROJ-3": "ddddddd",
        "agent/PROJ-4": "eeeeeee",
    }
    fake.branches["acme", "web"] = {}
    request = {
        "repositories": [
            {"name": "api", "url": "git@github.com:acme/api.git"},
            {"name": "web", "url": "https://github.com/acme/web"},
        ],
        "branch_prefix": "agent/",
    }
    code, lines, _ = read(url, request)
    assert code == 0
    assert lines == [
        {"kind": "branch", "repository": "api", "name": "agent/PROJ-1-fix", "head_sha": "bbbbbbb"},
        {"kind": "branch", "repository": "api", "name": "agent/PROJ-2", "head_sha": "ccccccc"},
        {"kind": "branch", "repository": "api", "name": "agent/PROJ-4", "head_sha": "eeeeeee"},
        {"kind": "end", "prs": [], "repositories": ["api", "web"]},
    ]
    assert fake.ops().count("Branches") == 3, "api's branches came on two pages"


def test_a_repository_it_cannot_read_is_left_off_the_end_and_the_rest_are_read(github: tuple[Fake, str]) -> None:
    fake, url = github
    fake.branches["acme", "api"] = {"agent/PROJ-1": "bbbbbbb"}
    request = {
        "repositories": [
            {"name": "lab", "url": "https://gitlab.com/acme/tools/lab.git"},
            {"name": "bare"},
            {"name": "gone", "url": "https://github.com/acme/gone"},
            {"name": "api", "url": "https://github.com/acme/api"},
        ],
        "branch_prefix": "agent/",
    }
    code, lines, err = read(url, request)
    assert code == 1
    assert lines[-1] == {"kind": "end", "prs": [], "repositories": ["api"]}
    assert (
        "cannot read repository lab: its clone URL 'https://gitlab.com/acme/tools/lab.git' names no repository" in err
    )
    assert "cannot read repository bare" in err
    assert "cannot read repository gone: GitHub refused it: no repository" in err


def test_a_repository_with_more_branches_than_the_bound_is_not_read(github: tuple[Fake, str]) -> None:
    fake, url = github
    fake.branches["acme", "api"] = {f"agent/PROJ-{n}": "bbbbbbb" for n in range(3)}
    request = {"repositories": [{"name": "api", "url": "https://github.com/acme/api"}], "branch_prefix": "agent/"}
    with mock.patch.object(repository_module, "MAX_BRANCHES", 2):
        code, lines, err = read(url, request)
    assert (code, lines) == (1, [{"kind": "end", "prs": [], "repositories": []}])
    assert "more than 2 branches under agent/" in err


# The review query


def test_the_review_query_names_the_prs_it_returns_on_the_repositories_host(github: tuple[Fake, str]) -> None:
    fake, url = github
    fake.branches["acme", "api"] = {}
    others = [f"https://github.com/acme/web/pull/{n}" for n in (4, 5)]
    fake.searches["is:pr review-requested:@me"] = [PR, "https://github.com/acme/api/issues/12", *others, PR]
    hosts: list[str] = []
    request = {
        "review_query": "is:pr review-requested:@me",
        "repositories": [{"name": "api", "url": "https://github.com/acme/api"}],
        "branch_prefix": "agent/",
    }
    code, lines, _ = read(url, request, hosts)
    assert code == 0
    assert lines == [{"kind": "end", "prs": [], "repositories": ["api"], "review_query": [PR, *others]}]
    assert hosts == ["github.com"]


def test_a_review_query_alone_runs_on_github_com(github: tuple[Fake, str]) -> None:
    fake, url = github
    fake.searches["is:pr"] = [PR]
    hosts: list[str] = []
    code, lines, _ = read(url, {"review_query": "is:pr"}, hosts)
    assert (code, lines, hosts) == (0, [{"kind": "end", "prs": [], "review_query": [PR]}], ["github.com"])


def test_a_review_query_that_matches_more_than_github_returns_is_not_read(github: tuple[Fake, str]) -> None:
    fake, url = github
    fake.searches["is:pr"], fake.search_count = [PR], 1001
    code, lines, err = read(url, {"review_query": "is:pr"})
    assert (code, lines) == (1, [{"kind": "end", "prs": []}])
    assert "it matches 1001, more than the 1000 GitHub returns" in err


# The request


def test_an_empty_request_reads_nothing_and_ends(github: tuple[Fake, str]) -> None:
    fake, url = github
    code, lines, _ = read(url, {"query": "project = PROJ", "tickets": [{"key": "PROJ-1"}]})
    assert (code, lines) == (0, [{"kind": "end", "prs": []}])
    assert not fake.seen


@pytest.mark.parametrize(
    ("request_", "message"),
    [
        ({"prs": PR}, "prs must be a list"),
        ({"prs": ["http://github.com/acme/api/pull/7"]}, "is not a PR's URL"),
        ({"prs": ["https://github.com/acme/api/pull/7/files"]}, "is not a PR's URL"),
        ({"prs": ["https://github.com/acme/api/issues/7"]}, "is not a PR's URL"),
        ({"prs": ["https://user@github.com/acme/api/pull/7"]}, "is not a PR's URL"),
        ({"prs": [PR] * 1001}, "at most 1000"),
        ({"repositories": {"name": "api"}, "branch_prefix": "agent/"}, "repositories must be a list"),
        ({"repositories": ["api"], "branch_prefix": "agent/"}, "is not a repository"),
        ({"repositories": [{"name": "-api"}], "branch_prefix": "agent/"}, "is not a repository's name"),
        ({"repositories": [{"name": "api"}]}, "need the branch prefix"),
        ({"repositories": [{"name": "api"}], "branch_prefix": "agent/ x"}, "need the branch prefix"),
        ({"review_query": " "}, "review query must be a string that is not blank"),
    ],
)
def test_the_reader_refuses_what_it_cannot_use(github: tuple[Fake, str], request_: object, message: str) -> None:
    fake, url = github
    code, lines, err = read(url, request_)
    assert code == 2
    assert not lines
    assert message in err
    assert not fake.seen


# What canopy records of it


def test_canopy_records_every_line_it_prints(github: tuple[Fake, str], canopy_env: CanopyEnv) -> None:
    fake, url = github
    pull = fake.pulls["acme", "api", 7]
    pull.labels, pull.merge_state = ["agent"], "BLOCKED"
    pull.contexts = [run("build", id_=11), status("deploy/approval", "PENDING"), run("lint", id_=12)]
    fake.branches["acme", "api"] = {"agent/PROJ-1": "bbbbbbb", "agent/PROJ-2": "ccccccc", "main": "aaaaaaa"}
    fake.searches["is:pr"] = [PR]
    conn = canopy_env.journal()
    request = observe.Request(
        prs=[PR],
        repositories=[observe.Repository("api", "https://github.com/acme/api.git")],
        branch_prefix="agent/",
        review_query="is:pr",
    )

    found = observe.observe(
        conn,
        config.load(canopy_env.root, canopy_env.user_file),
        InProcess(url),
        config.Source(kind="vcs", cmd="canopy-connect-github"),
        request,
        log=logs.for_tick(None),
    )

    assert (found.status, found.refused, found.missed) == (ConnectorRunStatus.OK, {}, None)
    assert found.recorded == {"pr": 1, "check": 3, "review": 4, "branch": 2}
    assert found.review_query_result == [PR]
    [pr] = records.fetch_all(conn, records.ObservedPr, sql.select("*").from_("observed_prs"))
    assert (json.loads(pr.labels), pr.mergeable_state, pr.head_sha) == (["agent"], MergeState.BLOCKED, HEAD)
    checks = records.fetch_all(conn, records.ObservedCheck, sql.select("*").from_("observed_checks").order_by("name"))
    assert [(c.name, c.status, c.run_id) for c in checks] == [
        ("build", CheckStatus.COMPLETED, 11),
        ("deploy/approval", CheckStatus.PENDING, None),
        ("lint", CheckStatus.COMPLETED, 12),
    ]
    branches = records.fetch_all(conn, records.ObservedBranch, sql.select("*").from_("observed_branches"))
    assert sorted((b.repository, b.name) for b in branches) == [("api", "agent/PROJ-1"), ("api", "agent/PROJ-2")]


@dataclass(frozen=True)
class InProcess:
    """A runner that runs the reader in this process against the stand-in at `url`, as canopy would run it."""

    url: str

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        timeout: float | None = None,
        on_start: Callable[[int], None] | None = None,
        on_line: Callable[[str], None] | None = None,
        stdout_to_file: bool = False,
    ) -> procs.Result:
        del cwd, env, timeout, on_start, stdout_to_file
        assert args[0] == "canopy-connect-github"
        result = invoke(connect.main, args[1:], stdin=stdin or "", obj=Hosts(lambda _: self.url, lambda _: "t"))
        for line in result.stdout.splitlines(keepends=True):
            if on_line is not None:
                on_line(line)
        return procs.Result(tuple(args), result.exit_code, result.stdout, result.stderr)

    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int:
        raise AssertionError(f"a connector is run, never spawned: {args}, {cwd}, {log_path}")


def test_endpoints_are_github_coms_api_host_or_the_servers_own() -> None:
    assert canopy_github.endpoint("github.com") == "https://api.github.com/graphql"
    assert canopy_github.endpoint("ghe.example.com") == "https://ghe.example.com/api/graphql"


# A `gh` logged in to ghe.example.com alone, that answers a token for any host, as it does for every host but
# github.com while GH_ENTERPRISE_TOKEN is set.
_GH = """#!/bin/sh
case "$*" in
  "auth status --json hosts --hostname ghe.example.com") echo '{"hosts":{"ghe.example.com":[]}}' ;;
  "auth status --json hosts --hostname "*) echo '{"hosts":{}}' ;;
  "auth token --hostname ghe.example.com") echo tok-ghe ;;
  "auth token --hostname "*) echo tok-enterprise ;;
  *) exit 1 ;;
esac
"""


def test_the_token_is_the_one_gh_holds_for_the_host(tmp_path: Path) -> None:
    executable(tmp_path / "gh", _GH)
    with mock.patch.dict(os.environ, {"PATH": f"{tmp_path}:{os.environ['PATH']}"}):
        assert canopy_github.gh_token("ghe.example.com") == "tok-ghe"


def test_no_token_is_read_for_a_host_gh_is_not_logged_in_to(tmp_path: Path) -> None:
    executable(tmp_path / "gh", _GH)
    with (
        mock.patch.dict(os.environ, {"PATH": f"{tmp_path}:{os.environ['PATH']}"}),
        pytest.raises(canopy_github.InputError, match=re.escape("run: gh auth login --hostname attacker.example")),
    ):
        canopy_github.gh_token("attacker.example")


def test_a_redirect_is_refused_and_the_token_does_not_follow_it() -> None:
    _Listener.heard.clear()
    with serving(_Listener) as listener, serving(_Redirect) as url:
        _Redirect.to = listener
        with pytest.raises(canopy_github.GitHubError, match="HTTP 302") as refused:
            canopy_github.Client(url, "t").query("query Viewer { viewer { login } }", {})
    assert refused.value.certain
    assert not _Listener.heard


def test_the_token_goes_only_in_the_header(github: tuple[Fake, str]) -> None:
    fake, url = github
    read(url, {"prs": [PR]})
    assert {auth for _, auth, _ in fake.seen} == {"bearer t"}


# Posting


def test_drafts_post_as_one_comment_review(github: tuple[Fake, str]) -> None:
    fake, url = github
    request = {
        "pr": PR,
        "delete_pending": None,
        "body": "Thanks, all done.",
        "replies": [{"comment": 501, "text": "Renamed.\n\nSee `app.py`."}, {"comment": 503, "text": "Kept it."}],
    }
    code, lines, _ = send(url, request)
    assert code == 0
    review = fake.pulls["acme", "api", 7].reviews[-1]
    assert (review.author, review.state, review.body) == ("me", "COMMENTED", "Thanks, all done.")
    threads = fake.pulls["acme", "api", 7].threads
    assert threads[0].comments[-1].body == "Renamed.\n\nSee `app.py`."
    assert threads[1].comments[-1].body == "Kept it."
    assert [line["kind"] for line in lines] == ["as", "pending", "comment", "comment", "review", "end"]
    assert lines[0] == {"kind": "as", "login": "me"}
    assert lines[1] == {"kind": "pending", "review": review.node, "id": review.id}
    assert lines[2] == {
        "kind": "comment",
        "comment": 501,
        "id": threads[0].comments[-1].id,
        "url": f"{PR}#discussion_r{threads[0].comments[-1].id}",
    }
    assert lines[4]["id"] == review.id
    assert lines[-1] == {"kind": "end", "submitted": True}
    assert fake.ops().count("Submit") == 1


def test_staged_drafts_are_left_in_a_pending_review_for_the_operator_to_submit(github: tuple[Fake, str]) -> None:
    fake, url = github
    request = {
        "pr": PR,
        "submit": False,
        "body": "Thanks, all done.",
        "replies": [{"comment": 501, "text": "Renamed."}, {"comment": 503, "text": "Kept it."}],
    }
    code, lines, _ = send(url, request)
    assert code == 0
    review = fake.pulls["acme", "api", 7].reviews[-1]
    assert (review.author, review.state, review.body) == ("me", "PENDING", "Thanks, all done.")
    threads = fake.pulls["acme", "api", 7].threads
    assert [threads[0].comments[-1].body, threads[1].comments[-1].body] == ["Renamed.", "Kept it."]
    assert all(t.comments[-1].review == review.id for t in threads)
    assert [line["kind"] for line in lines] == ["as", "pending", "comment", "comment", "end"]
    assert lines[1] == {"kind": "pending", "review": review.node, "id": review.id}
    assert lines[2]["id"] == threads[0].comments[-1].id
    assert lines[-1] == {"kind": "end", "submitted": False, "staged": True}
    assert "Submit" not in fake.ops()


def test_a_staged_reviews_reactions_are_added_at_once_and_one_alone_stages_no_reply(github: tuple[Fake, str]) -> None:
    fake, url = github
    request = {
        "pr": PR,
        "submit": False,
        "replies": [{"comment": 501, "text": "Renamed.", "reaction": "+1"}, {"comment": 503, "reaction": "heart"}],
    }
    code, lines, _ = send(url, request)
    assert code == 0
    threads = fake.pulls["acme", "api", 7].threads
    assert threads[0].comments[0].reactions == [("me", "THUMBS_UP")]
    assert threads[1].comments[1].reactions == [("me", "HEART")]
    review = fake.pulls["acme", "api", 7].reviews[-1]
    assert review.state == "PENDING"
    assert [c.body for c in threads[0].comments if c.review == review.id] == ["Renamed."]
    assert not [c for c in threads[1].comments if c.review == review.id]
    assert [line["kind"] for line in lines] == ["as", "reaction", "reaction", "pending", "comment", "end"]
    assert lines[-1] == {"kind": "end", "submitted": False, "staged": True}


def test_a_staged_reply_that_fails_deletes_the_pending_review(github: tuple[Fake, str]) -> None:
    fake, url = github
    fake.fail["Reply"] = "refuse"
    code, lines, _ = send(url, {"pr": PR, "submit": False, "replies": [{"comment": 501, "text": "Renamed."}]})
    assert code == 1
    assert lines[-1] == {"kind": "end", "submitted": False}
    assert [r.state for r in fake.pulls["acme", "api", 7].reviews] == ["COMMENTED"]


SHA = "9b2f4c6e1a7d" * 3 + "9b2f"
NEW = [
    {"path": "src/retry.py", "line": 2, "text": "This loops forever."},
    {"path": "README.md", "line": 1, "text": "?"},
]


def test_a_review_of_a_commit_starts_a_thread_for_each_comment_then_submits(github: tuple[Fake, str]) -> None:
    fake, url = github
    code, lines, _ = send(url, {"pr": PR, "commit": SHA, "body": "Two things.", "comments": NEW})
    assert code == 0
    pull = fake.pulls["acme", "api", 7]
    review = pull.reviews[-1]
    assert (review.state, review.body, review.commit) == ("COMMENTED", "Two things.", SHA)
    started = pull.threads[-2:]
    assert [(t.path, t.line, [c.body for c in t.comments]) for t in started] == [
        ("src/retry.py", 2, ["This loops forever."]),
        ("README.md", 1, ["?"]),
    ]
    assert all(t.comments[0].review == review.id for t in started)
    assert [line["kind"] for line in lines] == ["as", "pending", "comment", "comment", "review", "end"]
    assert lines[2] == {
        "kind": "comment",
        "index": 1,
        "id": started[0].comments[0].id,
        "url": f"{PR}#discussion_r{started[0].comments[0].id}",
    }
    assert lines[3]["index"] == 2
    assert fake.ops().index("Submit") > max(i for i, op in enumerate(fake.ops()) if op == "Thread")


def test_a_comment_github_refuses_posts_nothing_of_the_review_and_is_named(github: tuple[Fake, str]) -> None:
    fake, url = github
    fake.fail["Thread"] = "refuse"
    code, lines, err = send(url, {"pr": PR, "commit": SHA, "body": "Two things.", "comments": NEW})
    assert code == 1
    assert "GitHub refused comment 1, on src/retry.py:2" in err
    assert lines[-1] == {"kind": "end", "submitted": False}
    assert [r.state for r in fake.pulls["acme", "api", 7].reviews] == ["COMMENTED"]
    assert "Submit" not in fake.ops()


def test_a_staged_review_of_a_commit_holds_its_comments_pending(github: tuple[Fake, str]) -> None:
    fake, url = github
    code, lines, _ = send(url, {"pr": PR, "commit": SHA, "comments": NEW, "submit": False})
    assert code == 0
    review = fake.pulls["acme", "api", 7].reviews[-1]
    assert (review.state, review.commit) == ("PENDING", SHA)
    assert [line["kind"] for line in lines] == ["as", "pending", "comment", "comment", "end"]
    assert lines[-1] == {"kind": "end", "submitted": False, "staged": True}


def test_a_body_alone_is_a_review_with_no_replies(github: tuple[Fake, str]) -> None:
    fake, url = github
    code, lines, _ = send(url, {"pr": PR, "body": "Fixed CI."})
    assert code == 0
    assert fake.pulls["acme", "api", 7].reviews[-1].body == "Fixed CI."
    assert [line["kind"] for line in lines] == ["as", "pending", "review", "end"]


def test_reactions_are_added_before_the_review_and_one_alone_posts_no_reply(github: tuple[Fake, str]) -> None:
    fake, url = github
    replies = [{"comment": 501, "text": "Renamed.", "reaction": "+1"}, {"comment": 502, "reaction": "heart"}]
    code, lines, _ = send(url, {"pr": PR, "replies": replies})
    assert code == 0
    assert [op for op in fake.ops() if op in {"React", "AddReview", "Submit"}] == [
        "React",
        "React",
        "AddReview",
        "Submit",
    ]
    first, second = fake.pulls["acme", "api", 7].threads
    assert first.comments[0].reactions == [("me", "THUMBS_UP")]
    assert second.comments[0].reactions == [("me", "HEART")]
    assert [c.body for c in second.comments] == ["Why?", "Because."]
    assert [line["kind"] for line in lines] == ["as", "reaction", "reaction", "pending", "comment", "review", "end"]
    assert lines[1] == {"kind": "reaction", "comment": 501, "reaction": "+1", "url": f"{PR}#discussion_r501"}
    assert lines[4]["comment"] == 501


def test_reactions_alone_open_no_review(github: tuple[Fake, str]) -> None:
    fake, url = github
    code, lines, _ = send(url, {"pr": PR, "replies": [{"comment": 503, "reaction": "rocket"}]})
    assert code == 0
    assert "AddReview" not in fake.ops()
    assert fake.pulls["acme", "api", 7].threads[1].comments[1].reactions == [("me", "ROCKET")]
    assert [line["kind"] for line in lines] == ["as", "reaction", "end"]
    assert lines[-1] == {"kind": "end", "submitted": True}


@pytest.mark.parametrize("failure", ["refuse", "500", "lost"])
def test_a_reaction_that_fails_or_may_have_landed_opens_no_review_and_ends_unsubmitted(
    github: tuple[Fake, str],
    failure: str,
) -> None:
    fake, url = github
    fake.fail["React"] = failure
    code, lines, _ = send(url, {"pr": PR, "replies": [{"comment": 501, "text": "Renamed.", "reaction": "eyes"}]})
    assert code == 1
    # Even when it may have landed, the `end` line is printed: GitHub adds a reaction once, so sending again is safe.
    assert "AddReview" not in fake.ops()
    assert lines == [{"kind": "as", "login": "me"}, {"kind": "end", "submitted": False}]


def test_a_review_that_fails_after_its_reactions_names_them(github: tuple[Fake, str]) -> None:
    fake, url = github
    fake.fail["Reply"] = "500"
    code, lines, _ = send(url, {"pr": PR, "replies": [{"comment": 501, "text": "Renamed.", "reaction": "+1"}]})
    assert code == 1
    assert [line["kind"] for line in lines] == ["as", "reaction", "pending", "end"]
    assert lines[-1] == {"kind": "end", "submitted": False}
    # The reaction stays: GitHub adds it once, so sending again adds nothing more.
    assert fake.pulls["acme", "api", 7].threads[0].comments[0].reactions == [("me", "THUMBS_UP")]
    del fake.fail["Reply"]
    assert send(url, {"pr": PR, "replies": [{"comment": 501, "text": "Renamed.", "reaction": "+1"}]})[0] == 0
    assert fake.pulls["acme", "api", 7].threads[0].comments[0].reactions == [("me", "THUMBS_UP")]


def test_a_reply_to_a_comment_the_pr_has_no_thread_for_posts_nothing(github: tuple[Fake, str]) -> None:
    fake, url = github
    code, lines, err = send(url, {"pr": PR, "replies": [{"comment": 501, "text": "a"}, {"comment": 999, "text": "b"}]})
    assert code == 2
    assert "no review thread with comment 999" in err
    assert "AddReview" not in fake.ops()
    assert lines == [{"kind": "as", "login": "me"}, {"kind": "end", "submitted": False}]


def test_a_pending_review_of_the_posters_own_fails_the_post_and_posts_nothing(github: tuple[Fake, str]) -> None:
    fake, url = github
    fake.pulls["acme", "api", 7].reviews.append(Review(node="PRR_9", id=109, author="me", state="PENDING", at=None))
    code, lines, err = send(url, {"pr": PR, "replies": [{"comment": 501, "text": "Renamed."}]})
    assert code == 1
    assert "one pending review" in err
    assert lines[-1] == {"kind": "end", "submitted": False}
    assert "Reply" not in fake.ops()


def test_a_reply_that_fails_deletes_the_pending_review(github: tuple[Fake, str]) -> None:
    fake, url = github
    fake.fail["Reply"] = "500"
    code, lines, _ = send(url, {"pr": PR, "replies": [{"comment": 501, "text": "Renamed."}]})
    assert code == 1
    assert lines[-1] == {"kind": "end", "submitted": False}
    assert [r.state for r in fake.pulls["acme", "api", 7].reviews] == ["COMMENTED"]


def test_a_pending_review_that_cannot_be_deleted_is_named(github: tuple[Fake, str]) -> None:
    fake, url = github
    fake.fail.update({"Submit": "refuse", "Delete": "500"})
    code, lines, _ = send(url, {"pr": PR, "body": "Fixed CI."})
    assert code == 1
    assert lines[-1] == {"kind": "end", "submitted": False, "pending": lines[1]["review"]}


def test_a_submit_that_may_have_reached_github_prints_no_end(github: tuple[Fake, str]) -> None:
    fake, url = github
    fake.fail["Submit"] = "500"
    code, lines, err = send(url, {"pr": PR, "replies": [{"comment": 501, "text": "Renamed."}]})
    assert code == 1
    assert "the outcome is unknown" in err
    assert [line["kind"] for line in lines] == ["as", "pending"]
    assert "Delete" not in fake.ops()


def test_a_pending_review_opened_without_a_reply_is_deleted(github: tuple[Fake, str]) -> None:
    fake, url = github
    fake.fail["AddReview"] = "lost"
    code, lines, _ = send(url, {"pr": PR, "replies": [{"comment": 501, "text": "Renamed."}]})
    assert code == 1
    assert lines[-1] == {"kind": "end", "submitted": False}
    assert [r.state for r in fake.pulls["acme", "api", 7].reviews] == ["COMMENTED"]
    assert "Reply" not in fake.ops()


def test_a_reply_with_no_login_posts_nothing(github: tuple[Fake, str]) -> None:
    fake, url = github
    fake.viewer = ""
    code, lines, err = send(url, {"pr": PR, "delete_pending": "PRR_9", "body": "Fixed CI."})
    assert code == 1
    assert "no viewer's login" in err
    assert lines == [{"kind": "end", "submitted": False}]
    assert fake.ops() == ["Viewer"]


def test_a_failure_before_the_review_is_opened_posted_nothing(github: tuple[Fake, str]) -> None:
    fake, url = github
    fake.fail["Threads"] = "500"
    code, lines, _ = send(url, {"pr": PR, "replies": [{"comment": 501, "text": "Renamed."}]})
    assert code == 1
    assert lines[-1] == {"kind": "end", "submitted": False}


def test_a_pending_review_an_earlier_post_left_is_deleted_first(github: tuple[Fake, str]) -> None:
    fake, url = github
    pull = fake.pulls["acme", "api", 7]
    pull.reviews.append(Review(node="PRR_9", id=109, author="me", state="PENDING", at=None))
    pull.threads[0].comments.append(Comment(id=510, body="Renamed.", author="me", review=109))
    code, lines, _ = send(url, {"pr": PR, "delete_pending": "PRR_9", "replies": [{"comment": 501, "text": "Renamed."}]})
    assert code == 0
    assert "PRR_9" not in [r.node for r in pull.reviews]
    assert [c.body for c in pull.threads[0].comments] == ["Rename this.", "Renamed."]
    assert lines[-1] == {"kind": "end", "submitted": True}


def test_a_pending_review_already_gone_is_passed_over(github: tuple[Fake, str]) -> None:
    _, url = github
    code, _, _ = send(url, {"pr": PR, "delete_pending": "PRR_404", "body": "Fixed CI."})
    assert code == 0


@pytest.mark.parametrize(
    ("review", "message"),
    [
        (Review(node="PRR_9", id=109, author="me", state="COMMENTED"), "was submitted"),
        (Review(node="PRR_9", id=109, author="alice", state="PENDING", at=None), "is not a review of this PR by me"),
    ],
)
def test_only_the_posters_own_pending_review_is_deleted(github: tuple[Fake, str], review: Review, message: str) -> None:
    fake, url = github
    fake.pulls["acme", "api", 7].reviews.append(review)
    code, lines, err = send(url, {"pr": PR, "delete_pending": "PRR_9", "body": "Fixed CI."})
    assert code == 2
    assert message in err
    assert "Delete" not in fake.ops()
    assert "AddReview" not in fake.ops()
    assert lines[-1] == {"kind": "end", "submitted": False}


def test_a_tickets_draft_posts_one_issue_comment(github: tuple[Fake, str]) -> None:
    fake, url = github
    issue = "https://github.com/acme/api/issues/12"
    code, lines, _ = send(url, {"issue": issue, "ticket": "GH-12", "body": "Which base should this target?"})
    assert code == 0
    assert fake.issue_comments == [("I_12", "Which base should this target?")]
    assert [line["kind"] for line in lines] == ["as", "comment", "end"]
    assert lines[-1] == {"kind": "end", "submitted": True}


def test_an_issue_comment_that_may_have_posted_prints_no_end(github: tuple[Fake, str]) -> None:
    fake, url = github
    fake.fail["Comment"] = "500"
    code, lines, _ = send(url, {"issue": "https://github.com/acme/api/issues/12", "ticket": "GH-12", "body": "?"})
    assert code == 1
    assert [line["kind"] for line in lines] == ["as"]


@pytest.mark.parametrize(
    ("request_", "message"),
    [
        ({"issue": "https://github.com/acme/api/issues/12", "ticket": "GH-13", "body": "?"}, "is not issue #12's key"),
        ({"issue": "https://github.com/acme/api/pull/12", "ticket": "GH-12", "body": "?"}, "is not an issue's URL"),
        ({"pr": PR}, "nothing to post"),
        ({"pr": PR, "body": "  "}, "the body is empty"),
        ({"pr": PR, "replies": [{"comment": 501}]}, "the reply is empty"),
        ({"pr": PR, "replies": [{"text": "x"}]}, "the id of the review comment"),
        ({"pr": PR, "replies": [{"comment": 501, "reaction": "thumbsup"}]}, "a reply's reaction must be one of +1"),
        ({"pr": PR, "replies": [{"comment": 501, "text": "", "reaction": "+1"}]}, "the reply is empty"),
        ({"pr": PR, "replies": "x"}, "replies must be a list"),
        ({"pr": PR, "body": "x" * 65537}, "longer than GitHub's"),
        ({"pr": PR, "body": "x", "delete_pending": 3}, "delete_pending must be"),
        ({"pr": PR, "body": "x", "submit": "no"}, "submit must be true or false"),
        ({"pr": PR, "comments": [{"path": "a", "line": 1, "text": "x"}]}, "comments need the commit"),
        ({"pr": PR, "commit": "abc1234", "body": "x"}, "commit must be a commit's full id"),
        ({"pr": PR, "commit": SHA, "comments": [{"path": "a", "line": "1", "text": "x"}]}, "a line, and its text"),
        ({"pr": PR, "commit": SHA, "comments": [{"path": "a", "line": 1}]}, "the comment is empty"),
        ({"pr": PR, "commit": SHA, "comments": "x"}, "comments must be a list"),
    ],
)
def test_the_poster_refuses_what_it_cannot_use(github: tuple[Fake, str], request_: object, message: str) -> None:
    fake, url = github
    code, lines, err = send(url, request_)
    assert code == 2
    assert not lines
    assert message in err
    assert not fake.seen


@pytest.mark.parametrize("main", [connect.main, post.main], ids=["connect", "post"])
def test_the_command_line_is_read_before_stdin(main: click.Command) -> None:
    helped = invoke(main, ["--help"], stdin="not JSON")
    assert helped.exit_code == 0
    assert helped.stdout.startswith(f"Usage: {main.name} [OPTIONS]")
    refused = invoke(main, ["--nope"], stdin="not JSON")
    assert refused.exit_code == 2
    assert "No such option '--nope'" in refused.stderr
    assert "stdin" not in refused.stderr
