"""canopy's Jira connector (DESIGN §30), against a local stand-in for Jira Cloud's REST API."""

import contextlib
import io
import json
import os
import threading
import urllib.parse
from collections.abc import Callable, Generator, Mapping, Sequence
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar, override
from unittest import mock

import canopy_jira
import pytest
from canopy_jira import connect

from canopy.core import config, db, observe, records, sql
from canopy.core.config import Source
from canopy.core.vocab import ConnectorRunStatus, TicketState
from canopy.infra import logs, procs
from tests.conftest import CanopyEnv

#: What the stand-in pages by: smaller than the connector asks for, so every read crosses a page.
PAGE = 2
EMAIL = "op@example.com"
TOKEN = "ATATT-secret-token"  # noqa: S105


def doc(*paragraphs: str) -> dict[str, Any]:
    """An Atlassian Document Format document of plain paragraphs, as Jira's v3 API sends text."""
    content = [{"type": "paragraph", "content": [{"type": "text", "text": p}]} for p in paragraphs]
    return {"type": "doc", "version": 1, "content": content}


def labelled(at: str, added: Sequence[str], before: Sequence[str] = ()) -> dict[str, Any]:
    """A changelog entry adding `added` to the labels `before`."""
    item = {
        "field": "labels",
        "fieldtype": "jira",
        "fieldId": "labels",
        "fromString": " ".join(before),
        "toString": " ".join([*before, *added]),
    }
    return {"id": at, "created": at, "items": [item]}


@dataclass
class Comment:
    id: str
    created: str
    body: object = None
    author: str | None = "acc-alice"


@dataclass
class Issue:
    key: str
    summary: str = "Fix the build"
    description: object = None
    category: str = "indeterminate"
    labels: list[str] = field(default_factory=list[str])
    updated: str = "2026-10-18T09:00:00.000+0000"
    blocked_by: list[str] = field(default_factory=list[str])
    blocks: list[str] = field(default_factory=list[str])
    comments: list[Comment] = field(default_factory=list[Comment])
    history: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])


@dataclass
class Jira:
    """Jira's state, and what each request should do.

    `query` is the keys the JQL search returns, in order. `inline` is how many changelog entries a fetch carries, the
    newest; None for all. `fail` maps a path to the HTTP status it answers with.
    """

    issues: dict[str, Issue] = field(default_factory=dict[str, Issue])
    query: list[str] = field(default_factory=list[str])
    inline: int | None = None
    #: Whether a fetch's changelog says how many entries the whole one has.
    totals: bool = True
    fail: dict[str, int] = field(default_factory=dict[str, int])
    #: Each request: its method, path, query, Authorization header, and body.
    seen: list[tuple[str, str, dict[str, str], str | None, Any]] = field(
        default_factory=list[tuple[str, str, dict[str, str], str | None, Any]]
    )

    def add(self, *issues: Issue) -> None:
        for issue in issues:
            self.issues[issue.key] = issue

    def paths(self) -> list[str]:
        return [f"{method} {path}" for method, path, _, _, _ in self.seen]

    def handle(
        self, method: str, path: str, params: Mapping[str, str], body: Mapping[str, Any] | None
    ) -> Mapping[str, Any]:
        if body is not None and (method, path) == ("POST", "/rest/api/3/search/jql"):
            start = int(body.get("nextPageToken") or 0)
            keys = self.query[start : start + PAGE]
            reply: dict[str, Any] = {"issues": [self.node(self.issues[k]) for k in keys]}
            if start + PAGE < len(self.query):
                reply["nextPageToken"] = str(start + PAGE)
            return reply
        if body is not None and (method, path) == ("POST", "/rest/api/3/issue/bulkfetch"):
            log = "changelog" in body.get("expand", [])
            found = [self.issues[k] for k in body["issueIdsOrKeys"] if k in self.issues]
            return {"issues": [self.node(i, changelog=log) for i in found], "issueErrors": []}
        key, _, what = path.removeprefix("/rest/api/3/issue/").partition("/")
        issue = self.issues[urllib.parse.unquote(key)]
        start = int(params["startAt"])
        if what == "comment":
            ordered = sorted(issue.comments, key=lambda c: c.created, reverse=params.get("orderBy") == "-created")
            page = [self.comment(c) for c in ordered[start : start + PAGE]]
            return {"startAt": start, "maxResults": PAGE, "total": len(ordered), "comments": page}
        assert what == "changelog", path
        values = issue.history[start : start + PAGE]
        return {
            "startAt": start,
            "total": len(issue.history),
            "isLast": start + PAGE >= len(issue.history),
            "values": values,
        }

    def node(self, issue: Issue, *, changelog: bool = False) -> dict[str, Any]:
        blocks = {"name": "Blocks", "inward": "is blocked by", "outward": "blocks"}
        links = [{"type": blocks, "inwardIssue": {"key": k}} for k in issue.blocked_by]
        links += [{"type": blocks, "outwardIssue": {"key": k}} for k in issue.blocks]
        relates = {"name": "Relates", "inward": "relates to", "outward": "relates to"}
        links.append({"type": relates, "inwardIssue": {"key": "OTHER-1"}})
        found: dict[str, Any] = {
            "id": f"1{len(issue.key)}",
            "key": issue.key,
            "fields": {
                "summary": issue.summary,
                "description": issue.description,
                "status": {"name": "Whatever it is called", "statusCategory": {"key": issue.category}},
                "labels": issue.labels,
                "updated": issue.updated,
                "issuelinks": links,
            },
        }
        if changelog:
            shown = issue.history if self.inline is None else issue.history[len(issue.history) - self.inline :]
            found["changelog"] = {"startAt": 0, "maxResults": len(shown), "histories": shown}
            if self.totals:
                found["changelog"]["total"] = len(issue.history)
        return found

    @staticmethod
    def comment(c: Comment) -> dict[str, Any]:
        found: dict[str, Any] = {"id": c.id, "created": c.created, "body": c.body}
        if c.author is not None:
            found["author"] = {"accountId": c.author, "displayName": "Alice"}
        return found


class _Api(BaseHTTPRequestHandler):
    jira: ClassVar[Jira]

    def do_GET(self) -> None:
        self._answer(None)

    def do_POST(self) -> None:
        self._answer(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))

    def _answer(self, body: Mapping[str, Any] | None) -> None:
        url = urllib.parse.urlsplit(self.path)
        params = dict(urllib.parse.parse_qsl(url.query))
        _Api.jira.seen.append((self.command, url.path, params, self.headers["Authorization"], body))
        status = _Api.jira.fail.get(url.path)
        if status is not None:
            self.send_response(status)
            self.end_headers()
            self.wfile.write(b'{"errorMessages": ["no"]}')
            return
        reply = _Api.jira.handle(self.command, url.path, params, body)
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

    def do_POST(self) -> None:
        _Listener.heard.append(self.headers["Authorization"])
        self.send_response(200)
        self.end_headers()

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
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def jira() -> Generator[tuple[Jira, str]]:
    """A stand-in for Jira Cloud's REST API, holding no tickets. Yields it and its URL."""
    fake = Jira()
    _Api.jira = fake
    with serving(_Api) as url:
        yield fake, url


@pytest.fixture
def credentials(tmp_path: Path) -> Path:
    """A credentials file of the operator's, closed to others."""
    path = tmp_path / "jira-credentials"
    path.write_text(f"{EMAIL}:{TOKEN}\n")
    path.chmod(0o600)
    return path


@dataclass(frozen=True)
class Read:
    """One run of the connector: its exit code, the lines it printed, and its stderr."""

    code: int
    lines: Sequence[Mapping[str, Any]]
    err: str

    def kinds(self) -> list[tuple[str, str]]:
        """Each line's kind and subject: a ticket's key, a comment's id."""
        return [(line["kind"], line.get("key") or line.get("id") or "") for line in self.lines]

    def end(self) -> Mapping[str, Any]:
        assert self.lines[-1]["kind"] == "end"
        return self.lines[-1]

    def ticket(self, key: str) -> Mapping[str, Any]:
        return next(line for line in self.lines if line["kind"] == "ticket" and line["key"] == key)


def read(url: str, request: object, credentials: Path, *, site: str = "acme.atlassian.net") -> Read:
    """Run the connector for `request`, against the stand-in at `url`."""
    out, err = io.StringIO(), io.StringIO()
    argv = ["--site", site, "--credentials-file", str(credentials)]
    with contextlib.redirect_stderr(err):
        code = connect.run(argv, io.StringIO(json.dumps(request)), out, endpoint_of=lambda _: url)
    return Read(code, [json.loads(line) for line in out.getvalue().splitlines()], err.getvalue())


# Reading


def test_a_watched_ticket_prints_its_ticket_its_new_comments_then_the_query_its_blockers_and_the_end(
    jira: tuple[Jira, str], credentials: Path
) -> None:
    fake, url = jira
    fake.add(
        Issue(
            "PROJ-1",
            summary="Fix  the\nbuild",
            description=doc("The build is red.", "See CI."),
            labels=["agent", "needs-human"],
            updated="2026-10-18T11:00:00.000+0200",
            blocked_by=["PROJ-9"],
            blocks=["PROJ-5"],
            comments=[
                Comment("101", "2026-10-18T08:00:00.000+0000", doc("old")),
                Comment("102", "2026-10-18T10:00:00.000+0000", doc("Which branch?")),
                Comment("103", "2026-10-18T10:30:00.000+0000", doc("main"), author=None),
            ],
            history=[
                labelled("2026-10-17T09:00:00.000+0000", ["agent"]),
                labelled("2026-10-18T09:30:00.000+0000", ["needs-human"], before=["agent"]),
            ],
        ),
        Issue("PROJ-2", labels=["agent"]),
        Issue("PROJ-3", category="done"),
        Issue("PROJ-9", summary="Upgrade the runner", category="done"),
    )
    fake.query = ["PROJ-2", "PROJ-1", "PROJ-3"]
    request = {"query": "project = PROJ", "tickets": [{"key": "PROJ-1", "comments_since": "2026-10-18T10:00:00Z"}]}

    found = read(url, request, credentials)

    assert (found.code, found.err) == (0, "")
    assert found.kinds() == [
        ("ticket", "PROJ-1"),
        ("comment", "102"),
        ("comment", "103"),
        ("ticket", "PROJ-2"),
        ("ticket", "PROJ-9"),
        ("end", ""),
    ]
    assert found.ticket("PROJ-1") == {
        "kind": "ticket",
        "key": "PROJ-1",
        "title": "Fix the build",
        "body": "The build is red.\nSee CI.",
        "state": "open",
        "labels": [
            {"name": "agent", "added_at": "2026-10-17T09:00:00+00:00"},
            {"name": "needs-human", "added_at": "2026-10-18T09:30:00+00:00"},
        ],
        "blockers": ["PROJ-9"],
        "updated_at": "2026-10-18T09:00:00+00:00",
    }
    assert found.lines[1:3] == [
        {
            "kind": "comment",
            "ticket": "PROJ-1",
            "id": "102",
            "author": "acc-alice",
            "time": "2026-10-18T10:00:00+00:00",
            "body": "Which branch?",
        },
        {
            "kind": "comment",
            "ticket": "PROJ-1",
            "id": "103",
            "author": "unknown",
            "time": "2026-10-18T10:30:00+00:00",
            "body": "main",
        },
    ]
    assert found.ticket("PROJ-2")["labels"] == [{"name": "agent"}], "a ticket only the query returned has no times"
    assert found.ticket("PROJ-9")["state"] == "closed"
    assert found.end() == {"kind": "end", "tickets": ["PROJ-1", "PROJ-2", "PROJ-9"], "query": ["PROJ-2", "PROJ-1"]}


def test_the_query_is_read_to_its_last_page(jira: tuple[Jira, str], credentials: Path) -> None:
    fake, url = jira
    keys = [f"PROJ-{n}" for n in range(1, 8)]
    fake.add(*(Issue(k) for k in keys))
    fake.query = keys

    found = read(url, {"query": "project = PROJ"}, credentials)

    assert found.end() == {"kind": "end", "tickets": keys, "query": keys}
    searches = [body for method, path, _, _, body in fake.seen if path.endswith("/search/jql")]
    assert [s.get("nextPageToken") for s in searches] == [None, "2", "4", "6"]
    assert all(s["jql"] == "project = PROJ" and "description" in s["fields"] for s in searches)


def test_a_query_past_its_bound_is_not_read_and_says_so(jira: tuple[Jira, str], credentials: Path) -> None:
    fake, url = jira
    fake.add(*(Issue(f"PROJ-{n}") for n in range(1, 5)))
    fake.query = list(fake.issues)

    with mock.patch.object(connect, "MAX_QUERY", 3):
        found = read(url, {"query": "project = PROJ"}, credentials)

    assert found.code == 1
    assert "query" not in found.end(), "a query cut short never reads as its result"
    assert "narrow tracker.query" in found.err


def test_comments_are_read_newest_first_and_stop_at_one_older_than_asked(
    jira: tuple[Jira, str], credentials: Path
) -> None:
    fake, url = jira
    times = [f"2026-10-{day:02}T10:00:00.000+0000" for day in range(1, 11)]
    fake.add(Issue("PROJ-1", comments=[Comment(str(100 + n), t, doc(f"c{n}")) for n, t in enumerate(times)]))

    found = read(url, {"tickets": [{"key": "PROJ-1", "comments_since": "2026-10-08T10:00:00+00:00"}]}, credentials)

    assert [line["id"] for line in found.lines if line["kind"] == "comment"] == ["107", "108", "109"]
    comment_pages = [p for method, path, p, _, _ in fake.seen if path.endswith("/comment")]
    assert [p["startAt"] for p in comment_pages] == ["0", "2"], "it stops at the page holding an older comment"
    assert all(p["orderBy"] == "-created" for p in comment_pages)

    every = read(url, {"tickets": [{"key": "PROJ-1"}]}, credentials)
    assert len([line for line in every.lines if line["kind"] == "comment"]) == len(times)


def test_a_changelog_cut_short_in_the_fetch_is_read_whole_on_its_own(jira: tuple[Jira, str], credentials: Path) -> None:
    fake, url = jira
    noise: list[dict[str, Any]] = [
        {"id": str(n), "created": f"2026-10-0{n}T00:00:00.000+0000", "items": []} for n in range(2, 7)
    ]
    fake.add(Issue("PROJ-1", labels=["agent"], history=[labelled("2026-10-01T00:00:00.000+0000", ["agent"]), *noise]))
    fake.inline = 2

    found = read(url, {"tickets": [{"key": "PROJ-1"}]}, credentials)

    assert found.ticket("PROJ-1")["labels"] == [{"name": "agent", "added_at": "2026-10-01T00:00:00+00:00"}]
    assert "GET /rest/api/3/issue/PROJ-1/changelog" in fake.paths()


def test_a_changelog_that_does_not_say_its_length_is_read_whole_on_its_own(
    jira: tuple[Jira, str], credentials: Path
) -> None:
    fake, url = jira
    fake.add(Issue("PROJ-1", labels=["agent"], history=[labelled("2026-10-01T00:00:00.000+0000", ["agent"])]))
    fake.totals = False
    fake.inline = 0

    found = read(url, {"tickets": [{"key": "PROJ-1"}]}, credentials)

    assert found.ticket("PROJ-1")["labels"] == [{"name": "agent", "added_at": "2026-10-01T00:00:00+00:00"}]


def test_a_ticket_without_labels_reads_no_changelog(jira: tuple[Jira, str], credentials: Path) -> None:
    fake, url = jira
    fake.add(Issue("PROJ-1", history=[{"id": "1", "created": "2026-10-01T00:00:00.000+0000", "items": []}]))
    fake.inline = 0

    read(url, {"tickets": [{"key": "PROJ-1"}]}, credentials)

    assert not [p for p in fake.paths() if p.endswith("/changelog")]


def test_a_ticket_jira_does_not_return_is_left_off_the_end_even_when_the_query_returns_it(
    jira: tuple[Jira, str], credentials: Path
) -> None:
    fake, url = jira
    fake.add(Issue("PROJ-1"), Issue("PROJ-2", comments=[Comment("201", "2026-10-18T10:00:00.000+0000")]))
    fake.query = ["PROJ-2"]
    fake.fail["/rest/api/3/issue/PROJ-2/comment"] = 500
    request = {"query": "x", "tickets": [{"key": "PROJ-1"}, {"key": "PROJ-2"}, {"key": "GONE-1"}]}

    found = read(url, request, credentials)

    assert found.code == 1
    assert found.kinds() == [("ticket", "PROJ-1"), ("end", "")]
    assert found.end() == {"kind": "end", "tickets": ["PROJ-1"], "query": ["PROJ-2"]}
    assert "cannot read GONE-1: Jira did not return it" in found.err
    assert "cannot read PROJ-2: HTTP 500" in found.err


def test_a_blocker_jira_does_not_return_is_named_and_its_ticket_still_read(
    jira: tuple[Jira, str], credentials: Path
) -> None:
    fake, url = jira
    fake.add(Issue("PROJ-1", blocked_by=["PROJ-8", "PROJ-9"]), Issue("PROJ-8", blocked_by=["PROJ-7"]))

    found = read(url, {"tickets": [{"key": "PROJ-1"}]}, credentials)

    assert found.code == 1
    assert found.end()["tickets"] == ["PROJ-1", "PROJ-8"], "a blocker's own blockers are not followed"
    assert "cannot read blocker PROJ-9" in found.err


def test_a_search_that_fails_reads_the_tickets_asked_and_no_query(jira: tuple[Jira, str], credentials: Path) -> None:
    fake, url = jira
    fake.add(Issue("PROJ-1"))
    fake.fail["/rest/api/3/search/jql"] = 400

    found = read(url, {"query": "nonsense ((", "tickets": [{"key": "PROJ-1"}]}, credentials)

    assert found.code == 1
    assert found.end() == {"kind": "end", "tickets": ["PROJ-1"]}
    assert "cannot read the query: HTTP 400" in found.err


def test_nothing_is_written_to_jira(jira: tuple[Jira, str], credentials: Path) -> None:
    fake, url = jira
    fake.add(Issue("PROJ-1", labels=["agent"], blocked_by=["PROJ-2"]), Issue("PROJ-2"))
    fake.query = ["PROJ-1"]

    read(url, {"query": "x", "tickets": [{"key": "PROJ-1"}]}, credentials)

    posts = {path for method, path, _, _, _ in fake.seen if method == "POST"}
    assert posts == {"/rest/api/3/search/jql", "/rest/api/3/issue/bulkfetch"}, "its posts are searches"


# What canopy records of it


def test_canopy_records_every_line_it_prints(jira: tuple[Jira, str], credentials: Path, canopy_env: CanopyEnv) -> None:
    fake, url = jira
    fake.add(
        Issue(
            "PROJ-1",
            labels=["agent"],
            blocked_by=["PROJ-9"],
            comments=[Comment("101", "2026-10-18T10:00:00.000+0000", doc("Which branch?"))],
            history=[labelled("2026-10-17T09:00:00.000+0000", ["agent"])],
        ),
        Issue("PROJ-2", labels=["agent"]),
        Issue("PROJ-9", category="done"),
    )
    fake.query = ["PROJ-1", "PROJ-2"]
    conn = canopy_env.journal()
    db.touch_ticket(conn, "PROJ-1", "repo")
    source = Source(
        kind="tracker", cmd=f"canopy-connect-jira --site acme.atlassian.net --credentials-file {credentials}"
    )
    request = observe.Request(query="project = PROJ", tickets=[observe.AskedTicket("PROJ-1")])

    found = observe.observe(
        conn,
        config.load(canopy_env.root, canopy_env.user_file),
        InProcess(url),
        source,
        request,
        log=logs.for_tick(None),
    )

    assert (found.status, found.refused, found.missed) == (ConnectorRunStatus.OK, {}, None)
    assert found.query_result == ["PROJ-1", "PROJ-2"]
    assert found.recorded == {"ticket": 3, "comment": 1}
    tickets = {
        t.key: t for t in records.fetch_all(conn, records.ObservedTicket, sql.select("*").from_("observed_tickets"))
    }
    assert tickets["PROJ-9"].state is TicketState.CLOSED
    assert json.loads(tickets["PROJ-1"].blockers) == ["PROJ-9"]


@dataclass(frozen=True)
class InProcess:
    """A runner that runs the connector in this process against the stand-in at `url`, as canopy would run it."""

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
        assert args[0] == "canopy-connect-jira"
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err):
            code = connect.run(args[1:], io.StringIO(stdin or ""), out, endpoint_of=lambda _: self.url)
        for line in out.getvalue().splitlines(keepends=True):
            if on_line is not None:
                on_line(line)
        return procs.Result(tuple(args), code, out.getvalue(), err.getvalue())

    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int:
        raise AssertionError(f"a connector is run, never spawned: {args}, {cwd}, {log_path}")


# The site, the credentials, and the request


def test_the_credentials_go_only_in_the_header_and_only_to_the_site(jira: tuple[Jira, str], credentials: Path) -> None:
    fake, url = jira
    fake.add(Issue("PROJ-1"))

    found = read(url, {"tickets": [{"key": "PROJ-1"}]}, credentials)

    assert {auth for _, _, _, auth, _ in fake.seen} == {"Basic b3BAZXhhbXBsZS5jb206QVRBVFQtc2VjcmV0LXRva2Vu"}
    assert all(TOKEN not in json.dumps([path, params, body]) for _, path, params, _, body in fake.seen)
    assert TOKEN not in json.dumps(found.lines) + found.err


def test_a_redirect_is_refused_and_the_credentials_do_not_follow_it(credentials: Path) -> None:
    _Listener.heard.clear()
    with serving(_Listener) as elsewhere, serving(_Redirect) as url:
        _Redirect.to = f"{elsewhere}/rest/api/3/search/jql"
        found = read(url, {"query": "x"}, credentials)
    assert found.code == 1
    assert "HTTP 302" in found.err
    assert not _Listener.heard


@pytest.mark.parametrize(
    ("site", "host"),
    [
        ("acme.atlassian.net", "acme.atlassian.net"),
        ("https://Acme.atlassian.net/", "acme.atlassian.net"),
        ("jira.example.com:8443", "jira.example.com:8443"),
    ],
)
def test_a_site_is_a_host(site: str, host: str) -> None:
    assert canopy_jira.parse_site(site) == host


@pytest.mark.parametrize(
    "site",
    [
        "http://acme.atlassian.net",
        "https://acme.atlassian.net/jira",
        "https://user@acme.atlassian.net",
        "acme.atlassian.net?x=1",
        "ftp://acme.atlassian.net",
        "",
    ],
)
def test_a_site_that_is_not_one_host_over_https_is_refused(
    jira: tuple[Jira, str], credentials: Path, site: str
) -> None:
    fake, url = jira
    found = read(url, {"query": "x"}, credentials, site=site)
    assert (found.code, found.lines) == (2, [])
    assert "is not a Jira site" in found.err
    assert not fake.seen


@pytest.mark.parametrize(
    ("text", "mode", "message"),
    [
        (f"{EMAIL}:{TOKEN}", 0o644, "is readable by others; run: chmod 600"),
        (TOKEN, 0o600, "must hold one line, EMAIL:API_TOKEN"),
        (f"{EMAIL}:", 0o600, "must hold one line, EMAIL:API_TOKEN"),
        (f"{EMAIL}:{TOKEN} extra", 0o600, "must hold one line, EMAIL:API_TOKEN"),
        (f"{EMAIL}:{TOKEN}\n{EMAIL}:{TOKEN}", 0o600, "must hold one line, EMAIL:API_TOKEN"),
    ],
)
def test_a_credentials_file_that_is_not_usable_is_refused_unquoted(
    jira: tuple[Jira, str], tmp_path: Path, text: str, mode: int, message: str
) -> None:
    fake, url = jira
    path = tmp_path / "jira-credentials"
    path.write_text(text)
    path.chmod(mode)

    found = read(url, {"query": "x"}, path)

    assert (found.code, found.lines) == (2, [])
    assert message in found.err
    assert TOKEN not in found.err
    assert not fake.seen


def test_a_missing_or_special_credentials_file_is_refused(jira: tuple[Jira, str], tmp_path: Path) -> None:
    _, url = jira
    assert "cannot read the credentials file" in read(url, {}, tmp_path / "none").err
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo, 0o600)
    assert "is not a regular file" in read(url, {}, fifo).err


def test_the_credentials_file_defaults_to_the_operators_config(tmp_path: Path) -> None:
    with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path)}):
        assert canopy_jira.default_credentials_file() == tmp_path / "canopy" / "jira-credentials"


@pytest.mark.parametrize(
    ("request_", "message"),
    [
        ([], "stdin is not a JSON object"),
        ({"query": "  "}, "the query must be JQL"),
        ({"tickets": "PROJ-1"}, "tickets must be a list"),
        ({"tickets": [{"key": "PROJ 1"}]}, "is not a ticket's key"),
        ({"tickets": ["PROJ-1"]}, "is not a ticket's key"),
        ({"tickets": [{"key": "PROJ-1", "comments_since": "yesterday"}]}, "is not an ISO 8601 time"),
        ({"tickets": [{"key": f"P-{n}"} for n in range(1001)]}, "at most 1000"),
    ],
)
def test_a_request_it_cannot_use_is_refused(
    jira: tuple[Jira, str], credentials: Path, request_: object, message: str
) -> None:
    fake, url = jira
    found = read(url, request_, credentials)
    assert (found.code, found.lines) == (2, [])
    assert message in found.err
    assert not fake.seen


def test_an_empty_request_reads_nothing_and_ends(jira: tuple[Jira, str], credentials: Path) -> None:
    fake, url = jira
    found = read(url, {"prs": ["https://github.com/acme/api/pull/7"]}, credentials)
    assert (found.code, found.lines) == (0, [{"kind": "end", "tickets": []}])
    assert not fake.seen


def test_help_never_reads_stdin(capsys: pytest.CaptureFixture[str]) -> None:
    class Unread(io.StringIO):
        @override
        def read(self, size: int | None = -1, /) -> str:
            raise AssertionError("read stdin")

    for flag in ("--help", "-h"):
        assert connect.run([flag], Unread(), io.StringIO()) == 0
        printed = capsys.readouterr().out
        assert printed.startswith("Usage: canopy-connect-jira [OPTIONS]")
        assert "--credentials-file" in printed


def test_a_command_line_it_cannot_use_is_a_usage_error_and_sends_nothing(
    jira: tuple[Jira, str], credentials: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake, url = jira
    assert connect.run([], io.StringIO("{}"), io.StringIO(), endpoint_of=lambda _: url) == 2
    assert "Missing option '--site'" in capsys.readouterr().err
    unknown = ["--site", "acme.atlassian.net", "--credentials-file", str(credentials), "--token", "x"]
    assert connect.run(unknown, io.StringIO("{}"), io.StringIO(), endpoint_of=lambda _: url) == 2
    assert "No such option '--token'" in capsys.readouterr().err
    assert not fake.seen


# Jira's rich text


def test_a_documents_text_keeps_its_blocks_lists_mentions_and_links() -> None:
    document = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Ask ", "marks": [{"type": "strong"}]},
                    {"type": "mention", "attrs": {"id": "acc-1", "text": "@Alice"}},
                    {"type": "text", "text": " about"},
                    {"type": "hardBreak"},
                    {"type": "inlineCard", "attrs": {"url": "https://example.com/x"}},
                    {"type": "emoji", "attrs": {"shortName": ":tada:", "text": "🎉"}},
                ],
            },
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "a"}]}],
                    },
                    {
                        "type": "listItem",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "b"}]}],
                    },
                ],
            },
            {"type": "codeBlock", "content": [{"type": "text", "text": "make all"}]},
            {"type": "paragraph", "content": [{"type": "date", "attrs": {"timestamp": "1792281600000"}}]},
            {"type": "rule"},
            {"type": "mediaSingle", "content": [{"type": "media", "attrs": {"id": "x"}}]},
        ],
    }
    assert canopy_jira.document_text(document) == (
        "Ask @Alice about\nhttps://example.com/x🎉\n- a\n- b\nmake all\n2026-10-18\n---"
    )


def test_a_documents_text_is_cut_and_a_string_is_taken_as_it_is() -> None:
    assert canopy_jira.document_text(doc("x" * (canopy_jira.MAX_BODY + 10))) == "x" * canopy_jira.MAX_BODY
    assert canopy_jira.document_text("h1. wiki text") == "h1. wiki text"
    assert canopy_jira.document_text(None) == ""
    deep: dict[str, Any] = {"type": "text", "text": "deep"}
    for _ in range(100):
        deep = {"type": "blockquote", "content": [deep]}
    assert canopy_jira.document_text(deep) == ""
