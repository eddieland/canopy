"""canopy's GitHub Issues connector (DESIGN §30), against a local stand-in for GitHub's GraphQL API."""

import json
import re
from collections.abc import Callable, Generator, Mapping, Sequence
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler
from itertools import starmap
from typing import Any, ClassVar, override
from unittest import mock

import canopy_github
import pytest
from canopy_github import Hosts, InputError, connect

from canopy.core import config, db, observe, records, sql
from canopy.core.vocab import ConnectorRunStatus, TicketState
from canopy.infra import logs
from tests.canopy_github.helpers import InProcess, serving
from tests.conftest import CanopyEnv, invoke

#: What the stand-in pages by: smaller than the connector asks for, so every read crosses a page.
PAGE = 2
REPO = "acme/api"


@dataclass
class Comment:
    id: int
    at: str
    body: str = "Which branch?"
    #: None for an account since deleted.
    author: str | None = "alice"
    bot: bool = False


@dataclass
class Blocker:
    number: int
    repository: str = REPO
    state: str = "OPEN"


@dataclass
class Issue:
    number: int
    title: str = "Fix the build"
    body: str | None = ""
    state: str = "OPEN"
    labels: list[str] = field(default_factory=list[str])
    #: Each label event, oldest first: when, and the label added.
    labeled: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    blocked_by: list[Blocker] = field(default_factory=list[Blocker])
    comments: list[Comment] = field(default_factory=list[Comment])
    #: Where GitHub says it is: another repository's for one moved there.
    repository: str = REPO
    updated: str = "2026-10-18T09:00:00Z"


@dataclass
class GitHub:
    """One repository's issues, and what each operation should do.

    `query` is what the search returns, in order: an issue's number, or `"PR"` for a pull request. `fail` maps an
    operation to `refuse` or `500`; `heavy` are issues a batch that names one is answered with a 502 for.
    """

    issues: dict[int, Issue] = field(default_factory=dict[int, Issue])
    #: Issues of other repositories the search may return, by number.
    elsewhere: dict[int, Issue] = field(default_factory=dict[int, Issue])
    query: list[int | str] = field(default_factory=list[int | str])
    search_count: int | None = None
    fail: dict[str, str] = field(default_factory=dict[str, str])
    heavy: set[int] = field(default_factory=set[int])
    #: Each request: its operation and variables.
    seen: list[tuple[str, dict[str, Any]]] = field(default_factory=list[tuple[str, dict[str, Any]]])

    def add(self, *found: Issue) -> None:
        for issue in found:
            self.issues[issue.number] = issue

    def ops(self) -> list[str]:
        return [op for op, _ in self.seen]

    def handle(self, op: str, document: str, variables: Mapping[str, Any]) -> Mapping[str, Any]:
        if op == "Issues":
            return self.batch(document, variables)
        if op == "IssueSearch":
            start = int(variables["after"] or 0)
            nodes = [self.search_node(n) for n in self.query]
            count = len(nodes) if self.search_count is None else self.search_count
            info = {"hasNextPage": start + PAGE < len(nodes), "endCursor": str(start + PAGE)}
            return {"data": {"search": {"issueCount": count, "pageInfo": info, "nodes": nodes[start : start + PAGE]}}}
        issue = self.issues[variables["number"]]
        if op == "Labeled":
            events = list(starmap(self.event, issue.labeled))
            found = {"timelineItems": backward(events, variables["before"])}
        elif op == "IssueComments":
            found = {"comments": backward([self.comment(c) for c in issue.comments], variables["before"])}
        else:
            raise AssertionError(f"unexpected operation {op}")
        return {"data": {"repository": {"issue": found}}}

    def batch(self, document: str, variables: Mapping[str, Any]) -> Mapping[str, Any]:
        """Each issue under its alias, `i0` and on, its number in `k0` and on."""
        # GitHub names a repository whatever its case.
        if f"{variables['owner']}/{variables['name']}".lower() != REPO:
            error = {"type": "NOT_FOUND", "path": ["repository"], "message": "no such repository"}
            return {"data": {"repository": None}, "errors": [error]}
        history = "...History" in document
        data: dict[str, Any] = {}
        errors: list[dict[str, Any]] = []
        i = 0
        while f"k{i}" in variables:
            issue = self.issues.get(variables[f"k{i}"])
            data[f"i{i}"] = None if issue is None else self.node(issue, history=history)
            if issue is None:
                errors.append({"type": "NOT_FOUND", "path": ["repository", f"i{i}"], "message": "no such issue"})
            i += 1
        return {"data": {"repository": data}, **({"errors": errors} if errors else {})}

    def search_node(self, found: int | str) -> dict[str, Any]:
        if found == "PR":
            return {"__typename": "PullRequest"}
        assert isinstance(found, int)
        issue = self.issues.get(found) or self.elsewhere[found]
        return {"__typename": "Issue", **self.node(issue, history=False)}

    def node(self, issue: Issue, *, history: bool) -> dict[str, Any]:
        node: dict[str, Any] = {
            "number": issue.number,
            "title": issue.title,
            "body": issue.body,
            "state": issue.state,
            "updatedAt": issue.updated,
            "repository": {"nameWithOwner": issue.repository},
            "labels": {
                "pageInfo": {"hasNextPage": len(issue.labels) > 100},
                "nodes": [{"name": n} for n in issue.labels],
            },
            "blockedBy": {
                "pageInfo": {"hasNextPage": False},
                "nodes": [
                    {"number": b.number, "state": b.state, "repository": {"nameWithOwner": b.repository}}
                    for b in issue.blocked_by
                ],
            },
        }
        if history:
            node["timelineItems"] = backward(list(starmap(self.event, issue.labeled)), None)
            node["comments"] = backward([self.comment(c) for c in issue.comments], None)
        return node

    @staticmethod
    def event(at: str, label: str) -> dict[str, Any]:
        return {"createdAt": at, "label": {"name": label}}

    @staticmethod
    def comment(comment: Comment) -> dict[str, Any]:
        author = (
            None
            if comment.author is None
            else {"__typename": "Bot" if comment.bot else "User", "login": comment.author}
        )
        return {"fullDatabaseId": str(comment.id), "createdAt": comment.at, "body": comment.body, "author": author}


def backward(nodes: Sequence[Mapping[str, Any]], before: str | None) -> dict[str, Any]:
    """The page of `nodes` that ends before the cursor `before`, or the last page, as `last:` reads one."""
    end = len(nodes) if before is None else int(before)
    start = max(end - PAGE, 0)
    return {"pageInfo": {"hasPreviousPage": start > 0, "startCursor": str(start)}, "nodes": list(nodes[start:end])}


class _Api(BaseHTTPRequestHandler):
    github: ClassVar[GitHub]

    def do_POST(self) -> None:
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        match = re.match(r"\s*query\s+(\w+)", request["query"])
        assert match, request["query"]
        op, variables = match.group(1), request["variables"]
        github = _Api.github
        github.seen.append((op, variables))
        names = {v for k, v in variables.items() if re.fullmatch(r"k\d+", k)}
        if github.fail.get(op) == "500" or (op == "Issues" and names & github.heavy):
            self.send_response(502)
            self.end_headers()
            self.wfile.write(b"bad gateway")
            return
        if github.fail.get(op) == "refuse":
            reply: Mapping[str, Any] = {"errors": [{"message": f"{op} refused"}]}
        else:
            reply = github.handle(op, request["query"], variables)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(reply).encode())

    @override
    def log_message(self, format: str, *args: Any) -> None:
        del format, args


@pytest.fixture
def github() -> Generator[tuple[GitHub, str]]:
    """A stand-in for one repository's issues on GitHub's GraphQL API. Yields it and its URL."""
    fake = GitHub()
    _Api.github = fake
    with mock.patch.object(canopy_github, "RETRY_PAUSES", (0.0, 0.0)), serving(_Api) as url:
        yield fake, url


def read(
    url: str,
    request: object,
    *,
    repo: str = REPO,
    hosts: list[str] | None = None,
    token_of: Callable[[str], str] = lambda _: "t",
) -> tuple[int, list[dict[str, Any]], str]:
    """Run the connector for `request` on `repo`. Returns its exit code, its lines, and its stderr."""

    def endpoint_of(host: str) -> str:
        if hosts is not None:
            hosts.append(host)
        return url

    result = invoke(connect.main, ["--repo", repo], stdin=json.dumps(request), obj=Hosts(endpoint_of, token_of))
    return result.exit_code, [json.loads(line) for line in result.stdout.splitlines()], result.stderr


def ticket(number: int, **fields: object) -> dict[str, object]:
    """A ticket's line as the connector prints an open issue with no labels or blockers, with `fields` changed."""
    line: dict[str, object] = {
        "kind": "ticket",
        "key": f"GH-{number}",
        "title": "Fix the build",
        "body": "",
        "state": "open",
        "labels": [],
        "blockers": [],
        "updated_at": "2026-10-18T09:00:00+00:00",
    }
    return line | fields


def test_a_ticket_asked_prints_its_line_with_its_labels_times_then_each_comment(github: tuple[GitHub, str]) -> None:
    fake, url = github
    fake.add(
        Issue(
            12,
            title="Fix the\nbuild",
            body="It fails on main.\n",
            labels=["agent", "bug"],
            labeled=[
                ("2026-10-17T09:00:00Z", "agent"),
                ("2026-10-17T10:00:00Z", "other"),
                ("2026-10-17T11:00:00Z", "agent"),
                ("2026-10-17T12:00:00Z", "other"),
                ("2026-10-17T13:00:00Z", "other"),
            ],
            comments=[
                Comment(501, "2026-10-18T10:00:00Z"),
                Comment(502, "2026-10-18T11:00:00Z", "On it.", author="ci", bot=True),
                Comment(503, "2026-10-18T12:00:00Z", "Gone.", author=None),
                Comment(504, "2026-10-18T13:00:00Z", "main."),
                Comment(505, "2026-10-18T14:00:00Z", "Thanks."),
            ],
        ),
    )

    code, lines, stderr = read(url, {"tickets": [{"key": "GH-12"}]})

    assert (code, stderr) == (0, "")
    assert lines[0] == ticket(
        12,
        title="Fix the build",
        body="It fails on main.",
        labels=[{"name": "agent", "added_at": "2026-10-17T11:00:00+00:00"}, {"name": "bug"}],
    ), "the newest add, read back past the first page; a label no event added has no time"
    assert [(c["id"], c["author"], c["time"]) for c in lines[1:-1]] == [
        ("501", "alice", "2026-10-18T10:00:00+00:00"),
        ("502", "ci[bot]", "2026-10-18T11:00:00+00:00"),
        ("503", "ghost", "2026-10-18T12:00:00+00:00"),
        ("504", "alice", "2026-10-18T13:00:00+00:00"),
        ("505", "alice", "2026-10-18T14:00:00+00:00"),
    ], "every page of them, oldest first"
    assert lines[1] == {
        "kind": "comment",
        "ticket": "GH-12",
        "id": "501",
        "author": "alice",
        "time": "2026-10-18T10:00:00+00:00",
        "body": "Which branch?",
    }
    assert lines[-1] == {"kind": "end", "tickets": ["GH-12"]}


def test_comments_are_read_back_only_to_the_first_one_older_than_asked(github: tuple[GitHub, str]) -> None:
    fake, url = github
    fake.add(Issue(12, comments=[Comment(500 + i, f"2026-10-18T1{i}:00:00Z") for i in range(8)]))

    _, lines, _ = read(url, {"tickets": [{"key": "GH-12", "comments_since": "2026-10-18T15:00:00+00:00"}]})

    assert [c["id"] for c in lines if c["kind"] == "comment"] == ["505", "506", "507"]
    assert fake.ops() == ["Issues", "IssueComments"], "the page holding an older one is the last read"


def test_the_tickets_are_read_many_to_a_query(github: tuple[GitHub, str]) -> None:
    fake, url = github
    fake.add(*(Issue(n) for n in range(1, 31)))

    code, lines, _ = read(url, {"tickets": [{"key": f"GH-{n}"} for n in range(1, 31)]})

    assert code == 0
    assert lines[-1]["tickets"] == [f"GH-{n}" for n in range(1, 31)]
    assert fake.ops() == ["Issues", "Issues"]


def test_a_batch_github_cannot_answer_is_read_in_halves_down_to_the_issue_it_cannot(github: tuple[GitHub, str]) -> None:
    fake, url = github
    fake.add(Issue(12), Issue(13))
    fake.heavy = {13}

    code, lines, stderr = read(url, {"tickets": [{"key": "GH-12"}, {"key": "GH-13"}]})

    assert code == 1
    assert lines == [ticket(12), {"kind": "end", "tickets": ["GH-12"]}]
    assert "cannot read GH-13" in stderr


def test_the_query_prints_each_open_issue_once_and_names_them_in_its_order(github: tuple[GitHub, str]) -> None:
    fake, url = github
    fake.add(
        Issue(3, labels=["agent"]),
        Issue(4, state="CLOSED"),
        Issue(5, comments=[Comment(501, "2026-10-18T10:00:00Z")]),
    )
    fake.query = [5, "PR", 4, 3, 5]

    code, lines, _ = read(url, {"query": "is:issue label:agent", "tickets": [{"key": "GH-5"}]})

    assert code == 0
    assert [(line["kind"], line.get("key")) for line in lines] == [
        ("ticket", "GH-5"),
        ("comment", None),
        ("ticket", "GH-3"),
        ("end", None),
    ], "a ticket asked is printed once, with its comments; a PR and a closed issue are passed over"
    assert lines[2] == ticket(3, labels=[{"name": "agent"}])
    assert lines[-1] == {"kind": "end", "tickets": ["GH-5", "GH-3"], "query": ["GH-5", "GH-3"]}


def test_a_query_that_returns_another_repositorys_issue_is_not_read(github: tuple[GitHub, str]) -> None:
    fake, url = github
    fake.add(Issue(3))
    fake.elsewhere[9] = Issue(9, repository="acme/web")
    fake.query = [3, 9]

    code, lines, stderr = read(url, {"query": "label:agent"})

    assert code == 1
    assert lines[-1] == {"kind": "end", "tickets": ["GH-3"]}, "no query: it was not read to its end"
    assert "acme/web#9" in stderr
    assert "repo:acme/api" in stderr


def test_a_query_that_matches_more_than_github_returns_is_not_read(github: tuple[GitHub, str]) -> None:
    fake, url = github
    fake.search_count = 1001

    code, lines, stderr = read(url, {"query": "is:issue"})

    assert (code, lines) == (1, [{"kind": "end", "tickets": []}])
    assert "more than the 1000" in stderr


def test_blockers_are_its_dependencies_and_its_bodys_lines_each_read_once(github: tuple[GitHub, str]) -> None:
    fake, url = github
    fake.add(
        Issue(
            12,
            body="Blocked by #8\nblocked by #12\nNot blocked by #10",
            blocked_by=[Blocker(7), Blocker(8), Blocker(3, repository="acme/web", state="CLOSED")],
        ),
        Issue(7, blocked_by=[Blocker(9)]),
        Issue(8, state="CLOSED"),
        Issue(9),
    )

    code, lines, _ = read(url, {"tickets": [{"key": "GH-12"}]})

    assert code == 0
    assert lines == [
        ticket(12, body="Blocked by #8\nblocked by #12\nNot blocked by #10", blockers=["GH-7", "GH-8"]),
        ticket(7, blockers=["GH-9"]),
        ticket(8, state="closed"),
        {"kind": "end", "tickets": ["GH-12", "GH-7", "GH-8"]},
    ], "a closed blocker elsewhere blocks nothing, its own number is no blocker, and a blocker's are not followed"


def test_a_ticket_an_open_issue_of_another_repository_blocks_is_not_read_whole(github: tuple[GitHub, str]) -> None:
    fake, url = github
    fake.add(Issue(12, blocked_by=[Blocker(3, repository="acme/web")]), Issue(13))

    code, lines, stderr = read(url, {"tickets": [{"key": "GH-12"}, {"key": "GH-13"}]})

    assert code == 1
    assert lines == [ticket(13), {"kind": "end", "tickets": ["GH-13"]}]
    assert "cannot read GH-12: it is blocked by acme/web#3" in stderr


def test_a_ticket_it_cannot_read_is_left_off_the_end_and_the_rest_are_read(github: tuple[GitHub, str]) -> None:
    fake, url = github
    fake.add(Issue(12), Issue(13, repository="acme/web"))

    code, lines, stderr = read(url, {"tickets": [{"key": k} for k in ("GH-12", "GH-13", "GH-99", "PROJ-1")]})

    assert code == 1
    assert lines == [ticket(12), {"kind": "end", "tickets": ["GH-12"]}]
    assert "cannot read GH-13: it was moved to acme/web" in stderr
    assert "cannot read GH-99: GitHub refused it: no such issue" in stderr
    assert "cannot read PROJ-1: it is not a key of GitHub Issues" in stderr


def test_a_repository_github_does_not_return_reads_none_of_its_tickets(github: tuple[GitHub, str]) -> None:
    _, url = github

    code, lines, stderr = read(url, {"tickets": [{"key": "GH-12"}]}, repo="acme/gone")

    assert (code, lines) == (1, [{"kind": "end", "tickets": []}])
    assert "cannot read GH-12" in stderr


def test_the_repository_is_read_on_its_own_host(github: tuple[GitHub, str]) -> None:
    fake, url = github
    fake.add(Issue(12))
    hosts: list[str] = []

    read(url, {"tickets": [{"key": "GH-12"}]}, hosts=hosts)
    code, lines, _ = read(url, {"tickets": [{"key": "GH-12"}]}, repo="GitHub.Example.com/Acme/API", hosts=hosts)

    assert hosts == ["github.com", "github.example.com"]
    assert (code, lines[-1]) == (0, {"kind": "end", "tickets": ["GH-12"]}), "its name, whatever its case"


def test_a_host_gh_holds_no_token_for_reads_nothing(github: tuple[GitHub, str]) -> None:
    fake, url = github

    def no_token(host: str) -> str:
        raise InputError(f"gh is not logged in to {host}")

    code, lines, stderr = read(url, {"tickets": [{"key": "GH-12"}]}, token_of=no_token)

    assert (code, lines, fake.seen) == (2, [], [])
    assert "gh is not logged in to github.com" in stderr


@pytest.mark.parametrize(
    ("repo", "request_", "message"),
    [
        ("acme", {}, "is not OWNER/NAME"),
        ("acme/..", {}, "is not OWNER/NAME"),
        (REPO, {"query": " "}, "not blank"),
        (REPO, {"tickets": "GH-1"}, "must be a list"),
        (REPO, {"tickets": [{"key": "GH 1"}]}, "is not a ticket's key"),
        (REPO, {"tickets": [{"key": "GH-1", "comments_since": "yesterday"}]}, "is not an ISO 8601 time"),
    ],
)
def test_the_connector_refuses_what_it_cannot_use(
    github: tuple[GitHub, str],
    repo: str,
    request_: object,
    message: str,
) -> None:
    fake, url = github

    code, lines, stderr = read(url, request_, repo=repo)

    assert (code, lines, fake.seen) == (2, [], [])
    assert message in stderr


def test_without_a_repository_it_is_the_vcs_source_and_passes_the_tickets_over(github: tuple[GitHub, str]) -> None:
    fake, url = github

    result = invoke(connect.main, stdin=json.dumps({"tickets": [{"key": "GH-12"}]}), obj=Hosts(lambda _: url))

    assert (result.exit_code, result.stdout.strip(), fake.seen) == (0, '{"kind":"end","prs":[]}', [])


def test_canopy_records_every_line_it_prints(github: tuple[GitHub, str], canopy_env: CanopyEnv) -> None:
    fake, url = github
    fake.add(
        Issue(
            12,
            labels=["agent"],
            labeled=[("2026-10-17T09:00:00Z", "agent")],
            blocked_by=[Blocker(9)],
            comments=[Comment(501, "2026-10-18T10:00:00Z")],
        ),
        Issue(13, labels=["agent"]),
        Issue(9, state="CLOSED"),
    )
    fake.query = [12, 13]
    conn = canopy_env.journal()
    db.touch_ticket(conn, "GH-12", "repo")
    request = observe.Request(query="repo:acme/api label:agent", tickets=[observe.AskedTicket("GH-12")])

    found = observe.observe(
        conn,
        config.load(canopy_env.root, canopy_env.user_file),
        InProcess(url),
        config.Source(kind="tracker", cmd=f"canopy-connect-github --repo {REPO}"),
        request,
        log=logs.for_tick(None),
    )

    assert (found.status, found.refused, found.missed) == (ConnectorRunStatus.OK, {}, None)
    assert found.query_result == ["GH-12", "GH-13"]
    assert found.recorded == {"ticket": 3, "comment": 1}
    tickets = {
        t.key: t for t in records.fetch_all(conn, records.ObservedTicket, sql.select("*").from_("observed_tickets"))
    }
    assert tickets["GH-9"].state is TicketState.CLOSED
    assert json.loads(tickets["GH-12"].blockers) == ["GH-9"]
    assert json.loads(tickets["GH-12"].labels) == [{"name": "agent", "added_at": "2026-10-17T09:00:00.000Z"}], (
        "as canopy writes a time"
    )
    [comment] = records.fetch_all(conn, records.ObservedComment, sql.select("*").from_("observed_comments"))
    assert (comment.ticket, comment.id, comment.author) == ("GH-12", "501", "alice")
