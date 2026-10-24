"""The local artifact store's tools, called over MCP as a run's agent calls them (DESIGN §38)."""

from __future__ import annotations

import contextlib
import itertools
import json
import os
import threading
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from canopy_artifacts import cli, server
from canopy_artifacts.store import (
    LIST_PAGE,
    MAX_BODY,
    MAX_FEED,
    MAX_ORIGIN,
    OPERATOR,
    Scope,
    Store,
    agent,
    open_store,
)

from canopy.core import artifact_feed, conversation
from canopy.runs import worker
from tests.conftest import invoke

NAMESPACE = "canopy/operator"
#: A report as a worker publishes it: the passage people comment on sits in markup.
REPORT = """<html><head><title>Cache report</title></head><body>
<h1>Cache report</h1>
<p>The cache is <em>slow</em> under load, because every miss takes the lock.</p>
<p>We should shard it.</p>
</body></html>"""
#: The report's next version: the first passage kept word for word, the second reworded.
REVISED = """<html><body>
<h1>Cache report, revised</h1>
<p>Measured again: the cache is slow under load, because every miss takes the lock.</p>
<p>Sharding it is the plan.</p>
</body></html>"""
EIGHT = [
    "artifact_publish",
    "artifact_read",
    "artifact_list",
    "thread_list",
    "comment_feed",
    "comment_reply",
    "comment_create",
    "thread_resolve",
]


class Client:
    """Calls a store's tools through its MCP server, one JSON-RPC message at a time."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self._ids = itertools.count(1)

    def request(self, method: str, params: Mapping[str, object] | None = None) -> dict[str, Any]:
        line = json.dumps({"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params or {}})
        response = server.answer(line.encode(), self.store)
        assert response is not None
        return response

    def result(self, name: str, **arguments: object) -> str:
        """Call a tool, and return its result."""
        result = self.request("tools/call", {"name": name, "arguments": arguments})["result"]
        assert result["isError"] is False, result
        [content] = result["content"]
        return str(content["text"])

    def call(self, name: str, **arguments: object) -> dict[str, Any]:
        """Call a tool that succeeds, and return what it returned."""
        return json.loads(self.result(name, **arguments))

    def refused(self, name: str, **arguments: object) -> str:
        """Call a tool that refuses, and return its code."""
        result = self.request("tools/call", {"name": name, "arguments": arguments})["result"]
        assert result["isError"] is True, result
        refusal = json.loads(result["content"][0]["text"])
        assert refusal["message"]
        return refusal["code"]

    def feed(self, **arguments: object) -> list[dict[str, Any]]:
        """Read a page of the feed, its end line last."""
        return [json.loads(line) for line in self.result("comment_feed", **arguments).splitlines()]

    def publish(self, content: str = REPORT, **arguments: object) -> dict[str, Any]:
        return self.call(
            "artifact_publish",
            title="Cache report",
            content_type="text/html",
            content=content,
            **arguments,
        )


#: Opens another store on the test's directory, held to a scope of its own.
type Opener = Callable[[Scope], Client]


@contextlib.contextmanager
def opened(directory: Path, scope: Scope) -> Iterator[Store]:
    """Open the store in `directory`, held to `scope`, and close it when the block ends."""
    store = open_store(directory, scope)
    try:
        yield store
    finally:
        store.close()


@pytest.fixture
def store_dir(tmp_path: Path) -> Path:
    return tmp_path / "artifacts"


@pytest.fixture
def client(store_dir: Path) -> Iterator[Client]:
    with opened(store_dir, Scope(NAMESPACE, agent("implement"))) as store:
        yield Client(store)


@pytest.fixture
def opener(store_dir: Path) -> Iterator[Opener]:
    """Open more stores on the same directory, each held to a scope of its own, all closed when the test ends."""
    stores: list[Store] = []

    def open_one(scope: Scope) -> Client:
        stores.append(open_store(store_dir, scope))
        return Client(stores[-1])

    yield open_one
    for store in stores:
        store.close()


def test_a_published_artifact_reads_back_with_its_visible_text(client: Client) -> None:
    published = client.publish(origin={"canopy.ticket": "PROJ-1"})
    assert published["version"] == 1
    assert published["url"] == f"canopy-artifacts:{published['artifact_id']}/1"
    read = client.call("artifact_read", artifact_id=published["artifact_id"])
    assert read["content"] == REPORT
    assert read["text"] == (
        "Cache report The cache is slow under load, because every miss takes the lock. We should shard it."
    )
    assert read["artifact"]["namespace"] == NAMESPACE
    assert read["artifact"]["origin"] == {"canopy.ticket": "PROJ-1"}
    assert read["version"]["content_type"] == "text/html"
    assert len(read["version"]["sha256"]) == 64


def test_a_new_version_keeps_a_threads_anchor_and_a_reworded_passage_reads_passage_gone(client: Client) -> None:
    artifact = client.publish()["artifact_id"]
    kept = client.call(
        "comment_create",
        artifact_id=artifact,
        anchor={"exact": "every miss takes the lock", "prefix": "is slow under load, because", "suffix": "."},
        body="Which lock?",
    )
    reworded = client.call(
        "comment_create",
        artifact_id=artifact,
        anchor={"exact": "We should shard it."},
        body="By what key?",
    )
    whole = client.call("comment_create", artifact_id=artifact, body="Nice report.")

    assert client.publish(REVISED, artifact_id=artifact)["version"] == 2

    threads = {t["id"]: t for t in client.call("thread_list", artifact_id=artifact)["threads"]}
    assert threads[kept["thread_id"]]["anchor_status"] == "found"
    assert threads[reworded["thread_id"]]["anchor_status"] == "passage_gone"
    assert threads[whole["thread_id"]]["anchor_status"] is None
    assert threads[kept["thread_id"]]["anchored_version"] == 1
    # The first version still holds both passages.
    old = client.call("thread_list", artifact_id=artifact, version=1)["threads"]
    assert [t["anchor_status"] for t in old] == ["found", "found", None]


def test_an_html_anchor_is_taken_from_the_text_never_the_markup(client: Client) -> None:
    artifact = client.publish()["artifact_id"]
    across = client.call(
        "comment_create",
        artifact_id=artifact,
        anchor={"exact": "The cache is slow\n under   load"},
        body="Across the em.",
    )
    [thread] = client.call("thread_list", artifact_id=artifact)["threads"]
    assert thread["id"] == across["thread_id"]
    assert thread["anchor"] == {"exact": "The cache is slow under load", "prefix": "", "suffix": ""}
    assert client.refused("comment_create", artifact_id=artifact, anchor={"exact": "<em>slow</em>"}, body="x") == (
        "anchor_not_found"
    )
    assert client.refused(
        "comment_create",
        artifact_id=artifact,
        anchor={"exact": "Cache report</title>"},
        body="x",
    ) == ("anchor_not_found")


def test_threads_and_comments_carry_their_author_state_and_seq(client: Client) -> None:
    artifact = client.publish()["artifact_id"]
    first = client.call("comment_create", artifact_id=artifact, anchor={"exact": "shard it"}, body="Why?")
    reply = client.call("comment_reply", thread_id=first["thread_id"], body="Contention.")
    assert reply["seq"] == first["seq"] + 1
    assert client.call("thread_resolve", thread_id=first["thread_id"], resolved=True) == {"state": "resolved"}

    assert client.call("thread_list", artifact_id=artifact, state="open")["threads"] == []
    [thread] = client.call("thread_list", artifact_id=artifact, state="resolved")["threads"]
    assert thread["state"] == "resolved"
    assert [(c["id"], c["body"], c["seq"], c["via"]) for c in thread["comments"]] == [
        (first["comment_id"], "Why?", first["seq"], "mcp"),
        (reply["comment_id"], "Contention.", reply["seq"], "mcp"),
    ]
    assert thread["comments"][0]["author"] == {
        "id": "agent:implement",
        "display_name": "implement",
        "kind": "agent",
        "on_behalf_of": OPERATOR,
    }
    assert thread["comments"][0]["edited_at"] is None
    assert thread["comments"][0]["deleted_at"] is None


def test_resolving_or_reopening_is_a_change_and_doing_it_again_is_not(client: Client) -> None:
    artifact = client.publish()["artifact_id"]
    thread = client.call("comment_create", artifact_id=artifact, body="Overall?")["thread_id"]
    client.call("thread_resolve", thread_id=thread, resolved=True)
    client.call("thread_resolve", thread_id=thread, resolved=True)
    client.call("thread_resolve", thread_id=thread, resolved=False)
    *changes, end = client.feed()
    assert [(c["kind"], c["seq"], c["state"]) for c in changes] == [
        ("comment_created", 1, "open"),
        ("thread_resolved", 2, "open"),
        ("thread_reopened", 3, "open"),
    ]
    assert end == {"kind": "end", "through": 3}


def test_a_change_carries_ids_anchor_author_and_body_never_the_content(client: Client) -> None:
    artifact = client.publish(origin={"canopy.ticket": "PROJ-1"})["artifact_id"]
    made = client.call("comment_create", artifact_id=artifact, anchor={"exact": "shard it", "suffix": "."}, body="Hm.")
    [change, end] = client.feed()
    assert change["kind"] == "comment_created"
    assert change["seq"] == made["seq"]
    assert (change["artifact_id"], change["thread_id"], change["comment_id"]) == (
        artifact,
        made["thread_id"],
        made["comment_id"],
    )
    assert change["origin"] == {"canopy.ticket": "PROJ-1"}
    assert change["anchor"] == {"exact": "shard it", "prefix": "", "suffix": "."}
    assert change["author"]["kind"] == "agent"
    assert (change["via"], change["body"], change["state"]) == ("mcp", "Hm.", "open")
    assert change["at"]
    assert change["created_at"]
    assert change["edited_at"] is None
    assert change["deleted_at"] is None
    assert "content" not in change
    assert REPORT not in json.dumps(change)
    assert end == {"kind": "end", "through": made["seq"]}


def test_each_change_says_whether_its_passage_is_in_the_latest_version(client: Client) -> None:
    artifact = client.publish()["artifact_id"]
    kept = client.call("comment_create", artifact_id=artifact, anchor={"exact": "every miss takes the lock"}, body="A")
    reworded = client.call("comment_create", artifact_id=artifact, anchor={"exact": "shard it"}, body="B")
    client.call("comment_create", artifact_id=artifact, body="Overall?")
    assert [c["anchor_status"] for c in client.feed()[:-1]] == ["found", "found", None]

    client.publish(REVISED, artifact_id=artifact)
    client.call("comment_reply", thread_id=reworded["thread_id"], body="Still?")
    *changes, _ = client.feed()
    status = {c["comment_id"]: c["anchor_status"] for c in changes}
    # Each change is as its thread is when read, so the change made before the rewording reads it gone too.
    assert status[kept["comment_id"]] == "found"
    assert status[reworded["comment_id"]] == "passage_gone"
    assert changes[-1]["anchor_status"] == "passage_gone"


def test_the_feeds_cursor_misses_no_change_and_repeats_none_across_pages(client: Client) -> None:
    ours = client.publish(origin={"canopy.ticket": "PROJ-1"})["artifact_id"]
    theirs = client.publish(origin={"canopy.ticket": "PROJ-2"})["artifact_id"]
    wanted: list[int] = []
    seen: list[int] = []
    since = 0
    for round_ in range(7):
        # Changes land between page reads, on both tickets' artifacts.
        for _ in range(round_ % 3 + 1):
            wanted.append(client.call("comment_create", artifact_id=ours, body=f"ours {round_}")["seq"])
            client.call("comment_create", artifact_id=theirs, body=f"theirs {round_}")
        *changes, end = client.feed(origin={"canopy.ticket": "PROJ-1"}, since=since, limit=2)
        assert end["kind"] == "end"
        assert all(c["seq"] > since for c in changes)
        assert end["through"] >= since
        seen.extend(c["seq"] for c in changes)
        since = end["through"]
    while True:
        *changes, end = client.feed(origin={"canopy.ticket": "PROJ-1"}, since=since, limit=2)
        seen.extend(c["seq"] for c in changes)
        if end["through"] == since:
            break
        since = end["through"]
    assert seen == wanted
    # Past the last page, the cursor names the store's newest change, the other ticket's included.
    assert since == client.feed()[-2]["seq"]


def test_changes_committed_while_a_reader_pages_are_each_read_once(client: Client, store_dir: Path) -> None:
    artifact = client.publish()["artifact_id"]
    thread = client.call("comment_create", artifact_id=artifact, body="Start.")["thread_id"]
    writers = 4
    each = 25
    done = threading.Event()
    seen: list[int] = []

    def write(n: int) -> None:
        with opened(store_dir, Scope(NAMESPACE, agent(f"writer-{n}"))) as store:
            writer = Client(store)
            for i in range(each):
                writer.call("comment_reply", thread_id=thread, body=f"{n}.{i}")

    def read() -> None:
        with opened(store_dir, Scope(NAMESPACE, agent("reader"), read_only=True)) as store:
            reader = Client(store)
            since = 0
            while True:
                finished = done.is_set()
                *changes, end = reader.feed(since=since, limit=7)
                seen.extend(c["seq"] for c in changes)
                since = end["through"]
                if finished and not changes:
                    return
                if not changes:
                    # Caught up: let the writers in rather than spin, until they are done or a little passes.
                    done.wait(0.005)

    started = [threading.Thread(target=write, args=(n,)) for n in range(writers)]
    reading = threading.Thread(target=read)
    reading.start()
    for t in started:
        t.start()
    for t in started:
        t.join(timeout=60)
    done.set()
    reading.join(timeout=60)
    assert not reading.is_alive()
    assert seen == list(range(1, 2 + writers * each))


def test_artifacts_list_newest_first_a_page_at_a_time_by_origin(client: Client) -> None:
    made = [client.publish(origin={"canopy.ticket": f"PROJ-{i % 2}"})["artifact_id"] for i in range(LIST_PAGE + 3)]
    first = client.call("artifact_list")
    assert [a["id"] for a in first["artifacts"]] == made[::-1][:LIST_PAGE]
    second = client.call("artifact_list", cursor=first["next_cursor"])
    assert [a["id"] for a in second["artifacts"]] == made[::-1][LIST_PAGE:]
    assert second["next_cursor"] is None
    odd = client.call("artifact_list", origin={"canopy.ticket": "PROJ-1"})
    assert [a["id"] for a in odd["artifacts"]] == made[1::2][::-1]
    assert client.call("artifact_list", origin={"canopy.ticket": "PROJ-9"}) == {"artifacts": [], "next_cursor": None}


def test_origin_pairs_the_command_line_sets_win_over_the_callers(opener: Opener) -> None:
    client = opener(Scope(NAMESPACE, agent("implement"), {"canopy.ticket": "PROJ-1", "canopy.run": "7"}))
    artifact = client.publish(origin={"canopy.ticket": "PROJ-9", "topic": "cache"})["artifact_id"]
    origin = client.call("artifact_read", artifact_id=artifact)["artifact"]["origin"]
    assert origin == {"canopy.ticket": "PROJ-1", "canopy.run": "7", "topic": "cache"}


def test_another_namespaces_artifacts_are_out_of_scope(client: Client, opener: Opener) -> None:
    artifact = client.publish()["artifact_id"]
    thread = client.call("comment_create", artifact_id=artifact, body="Mine.")["thread_id"]
    other = opener(Scope("someone/else", agent("implement")))
    assert other.refused("artifact_read", artifact_id=artifact) == "out_of_scope"
    assert other.refused("thread_list", artifact_id=artifact) == "out_of_scope"
    assert other.refused("comment_create", artifact_id=artifact, body="x") == "out_of_scope"
    assert other.refused("comment_reply", thread_id=thread, body="x") == "out_of_scope"
    assert other.refused("thread_resolve", thread_id=thread, resolved=True) == "out_of_scope"
    assert other.refused(
        "artifact_publish",
        title="t",
        content_type="text/html",
        content="x",
        artifact_id=artifact,
    ) == ("out_of_scope")
    assert other.call("artifact_list") == {"artifacts": [], "next_cursor": None}
    # The other namespace's changes are left out, and its cursor still passes them.
    assert other.feed() == [{"kind": "end", "through": 1}]


def test_a_read_only_store_refuses_every_write_and_reads(client: Client, opener: Opener) -> None:
    artifact = client.publish()["artifact_id"]
    thread = client.call("comment_create", artifact_id=artifact, body="Mine.")["thread_id"]
    reader = opener(Scope(NAMESPACE, agent("source"), read_only=True))
    assert reader.refused("artifact_publish", title="t", content_type="text/markdown", content="x") == "read_only"
    assert reader.refused("comment_create", artifact_id=artifact, body="x") == "read_only"
    assert reader.refused("comment_reply", thread_id=thread, body="x") == "read_only"
    assert reader.refused("thread_resolve", thread_id=thread, resolved=True) == "read_only"
    assert reader.call("artifact_read", artifact_id=artifact)["content"] == REPORT
    assert [c["kind"] for c in reader.feed()] == ["comment_created", "end"]


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("artifact_read", {"artifact_id": "a_missing"}),
        ("thread_list", {"artifact_id": "a_missing"}),
        ("comment_create", {"artifact_id": "a_missing", "body": "x"}),
        ("comment_reply", {"thread_id": "t_missing", "body": "x"}),
        ("thread_resolve", {"thread_id": "t_missing", "resolved": True}),
        ("artifact_publish", {"title": "t", "content_type": "text/html", "content": "x", "artifact_id": "a_missing"}),
    ],
)
def test_an_id_the_store_does_not_have_is_not_found(client: Client, name: str, arguments: dict[str, object]) -> None:
    assert client.refused(name, **arguments) == "not_found"


def test_a_version_the_artifact_does_not_have_is_not_found(client: Client) -> None:
    artifact = client.publish()["artifact_id"]
    assert client.refused("artifact_read", artifact_id=artifact, version=2) == "not_found"
    assert client.refused("thread_list", artifact_id=artifact, version=2) == "not_found"
    # Past what SQLite holds is no version at all.
    assert client.refused("artifact_read", artifact_id=artifact, version=2**64) == "invalid"


def test_what_is_over_its_bound_is_too_long(client: Client) -> None:
    artifact = client.publish()["artifact_id"]
    thread = client.call("comment_create", artifact_id=artifact, body="x" * MAX_BODY)["thread_id"]
    assert client.refused("comment_reply", thread_id=thread, body="x" * (MAX_BODY + 1)) == "too_long"
    assert client.refused("comment_create", artifact_id=artifact, body="x" * (MAX_BODY + 1)) == "too_long"
    assert client.refused(
        "comment_create",
        artifact_id=artifact,
        anchor={"exact": "shard", "prefix": "p" * 33},
        body="x",
    ) == ("too_long")
    assert client.refused(
        "comment_create",
        artifact_id=artifact,
        anchor={"exact": "shard", "suffix": "s" * 33},
        body="x",
    ) == ("too_long")
    pairs = {f"k{i}": "v" for i in range(MAX_ORIGIN + 1)}
    assert client.refused("artifact_publish", title="t", content_type="text/html", content="x", origin=pairs) == (
        "too_long"
    )
    assert client.refused("artifact_publish", title="t" * 201, content_type="text/html", content="x") == "too_long"


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("artifact_publish", {"title": "t", "content_type": "text/plain", "content": "x"}),
        ("artifact_publish", {"title": " ", "content_type": "text/html", "content": "x"}),
        ("artifact_publish", {"title": "t", "content_type": "text/html"}),
        ("artifact_publish", {"title": "t", "content_type": "text/html", "content": "x", "public": True}),
        ("artifact_read", {"artifact_id": 7}),
        ("artifact_list", {"cursor": "next"}),
        ("comment_feed", {"limit": MAX_FEED + 1}),
        ("comment_feed", {"since": -1}),
        ("comment_feed", {"since": 2**64}),
        ("artifact_list", {"cursor": "9" * 30}),
        ("thread_resolve", {"thread_id": "t_1", "resolved": "yes"}),
        ("comment_reply", {"thread_id": "t_1", "body": "  \n"}),
    ],
)
def test_arguments_the_tool_cannot_use_are_invalid(client: Client, name: str, arguments: dict[str, object]) -> None:
    assert client.refused(name, **arguments) == "invalid"


def test_an_origin_is_set_when_an_artifact_is_made_and_kept_by_its_versions(client: Client) -> None:
    artifact = client.publish(origin={"canopy.ticket": "PROJ-1"})["artifact_id"]
    assert (
        client.refused(
            "artifact_publish",
            title="t",
            content_type="text/html",
            content="x",
            artifact_id=artifact,
            origin={"canopy.ticket": "PROJ-2"},
        )
        == "invalid"
    )
    client.publish(REVISED, artifact_id=artifact)
    assert client.call("artifact_read", artifact_id=artifact)["artifact"] == {
        "id": artifact,
        "title": "Cache report",
        "namespace": NAMESPACE,
        "origin": {"canopy.ticket": "PROJ-1"},
        "latest_version": 2,
        "created_at": mock.ANY,
    }


def test_it_serves_the_eight_tools_and_nothing_else(client: Client) -> None:
    hello = client.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})["result"]
    assert hello["protocolVersion"] == "2024-11-05"
    assert hello["capabilities"] == {"tools": {"listChanged": False}}
    assert (
        client.request("initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"]
        == (server.PROTOCOL_VERSIONS[0])
    )
    tools = client.request("tools/list")["result"]["tools"]
    assert [t["name"] for t in tools] == EIGHT
    schemas = json.dumps([t["inputSchema"] for t in tools])
    assert "$ref" not in schemas
    # No schema's title; the title field of artifact_publish stays.
    assert '"title": "' not in schemas
    publish = next(t for t in tools if t["name"] == "artifact_publish")["inputSchema"]
    assert all(field["description"] for field in publish["properties"].values())
    create = next(t for t in tools if t["name"] == "comment_create")["inputSchema"]
    assert create["properties"]["anchor"]["anyOf"][0]["properties"].keys() == {"exact", "prefix", "suffix"}
    assert client.request("resources/list")["error"]["code"] == server.METHOD_NOT_FOUND
    assert client.request("tools/call", {"name": "artifact_delete", "arguments": {}})["error"]["code"] == (
        server.INVALID_PARAMS
    )
    assert server.answer(b"{not json", client.store) == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": server.PARSE_ERROR, "message": "not a JSON message"},
    }
    assert server.answer(b'{"jsonrpc": "2.0", "method": "notifications/initialized"}', client.store) is None


def test_serve_answers_on_stdio_until_stdin_closes(store_dir: Path) -> None:
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "artifact_publish",
                "arguments": {"title": "Plan", "content_type": "text/markdown", "content": "# Plan"},
            },
        },
    ]
    served = invoke(
        cli.main,
        ["serve", "--store", str(store_dir), "--namespace", NAMESPACE, "--origin", "canopy.run=7"],
        stdin="".join(json.dumps(m) + "\n" for m in lines),
    )
    assert served.exit_code == 0
    answers = [json.loads(line) for line in served.stdout.splitlines()]
    assert [a["id"] for a in answers] == [1, 2]
    published = json.loads(answers[1]["result"]["content"][0]["text"])
    with opened(store_dir, Scope(NAMESPACE, agent("reader"))) as store:
        assert Client(store).call("artifact_read", artifact_id=published["artifact_id"])["artifact"]["origin"] == {
            "canopy.run": "7",
        }
    assert store_dir.stat().st_mode & 0o777 == 0o700


def test_in_a_run_canopy_starts_the_runs_environment_names_its_ticket_over_the_callers(store_dir: Path) -> None:
    """The variables canopy sets on a worker's run are the store's, so the worker cannot name another ticket."""
    publish = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "artifact_publish",
            "arguments": {
                "title": "Plan",
                "content_type": "text/markdown",
                "content": "# Plan",
                "origin": {artifact_feed.TICKET_KEY: "PROJ-9", "canopy.run": "1", "topic": "cache"},
            },
        },
    }
    run = {conversation.RUN_ID_ENV: "7", worker.TICKET_ENV: "PROJ-1", worker.WORKSPACE_ENV: "acme"}
    options = ["--namespace", NAMESPACE, "--origin", "canopy.run=3", "--origin", "a=b"]
    with mock.patch.dict(os.environ, run):
        served = invoke(cli.main, ["serve", "--store", str(store_dir), *options], stdin=json.dumps(publish) + "\n")
    assert served.exit_code == 0
    [answer] = [json.loads(line) for line in served.stdout.splitlines()]
    published = json.loads(answer["result"]["content"][0]["text"])
    with opened(store_dir, Scope(NAMESPACE, agent("reader"))) as store:
        assert Client(store).call("artifact_read", artifact_id=published["artifact_id"])["artifact"]["origin"] == {
            "canopy.workspace": "acme",
            artifact_feed.TICKET_KEY: "PROJ-1",
            "canopy.run": "7",
            "a": "b",
            "topic": "cache",
        }
    # A variable set to nothing names nothing, and outside a run there are none.
    assert cli.run_origin({worker.TICKET_ENV: "", conversation.RUN_ID_ENV: "7"}) == {"canopy.run": "7"}
    assert cli.run_origin({}) == {}


def test_a_store_directory_open_to_others_is_refused(store_dir: Path) -> None:
    store_dir.mkdir(mode=0o755)
    os.chmod(store_dir, 0o755)  # noqa: PTH101, S103  (past the umask: open to others is what is tested)
    refused = invoke(cli.main, ["serve", "--store", str(store_dir)])
    assert refused.exit_code == 2
    assert "open to others; run: chmod 700" in refused.stderr
    assert not (store_dir / "artifacts.db").exists()


def test_a_symlinked_store_directory_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    (tmp_path / "link").symlink_to(real)
    refused = invoke(cli.main, ["serve", "--store", str(tmp_path / "link")])
    assert refused.exit_code == 2
    assert "is not a directory" in refused.stderr


@pytest.mark.parametrize(
    "options",
    [["--origin", "no-equals"], ["--origin", "=v"], ["--namespace", "two words"], ["--agent", "two words"]],
)
def test_options_that_name_no_scope_are_refused(store_dir: Path, options: list[str]) -> None:
    assert invoke(cli.main, ["serve", "--store", str(store_dir), *options]).exit_code == 2
    assert not store_dir.exists()
