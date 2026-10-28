"""`canopy-artifacts feed`, canopy's `artifacts` source (DESIGN §30, §38): the feed past a cursor, then `end`."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from unittest import mock

import pytest
from canopy_artifacts import cli
from canopy_artifacts.store import Scope, Store, agent, open_store
from canopy_artifacts.text import Anchor

from canopy.core import artifact_feed, config, observe, records, sql
from canopy.core.config import Source
from canopy.core.vocab import AnchorStatus, AuthorKind, ConnectorRunStatus, ThreadState
from canopy.infra import logs, procs
from tests.conftest import CanopyEnv, invoke

NAMESPACE: Final = "canopy/operator"
PAGE: Final = """<html><body><p>The cache is slow under load.</p><p>We should shard it.</p></body></html>"""
REWORDED: Final = """<html><body><p>The cache is slow under load.</p><p>Sharding it is the plan.</p></body></html>"""


@pytest.fixture
def store_dir(tmp_path: Path) -> Path:
    return tmp_path / "artifacts"


@pytest.fixture
def store(store_dir: Path) -> Iterator[Store]:
    """The store, as a worker publishing for PROJ-1 writes to it."""
    opened = open_store(store_dir, Scope(NAMESPACE, agent("implement")))
    try:
        yield opened
    finally:
        opened.close()


def publish(store: Store, ticket: str = "PROJ-1", content: str = PAGE, artifact_id: str | None = None) -> str:
    """Publish PAGE, or a new version of `artifact_id`, for `ticket`; return the artifact's id."""
    origin = None if artifact_id is not None else {"canopy.ticket": ticket}
    found = store.publish(
        title="Cache report",
        content_type="text/html",
        content=content,
        origin=origin,
        artifact_id=artifact_id,
    )
    return str(found["artifact_id"])


def seq(made: Mapping[str, object]) -> int:
    """The `seq` of the change a write made."""
    found = made["seq"]
    assert isinstance(found, int)
    return found


def feed(store_dir: Path, since: int = 0, *options: str) -> list[dict[str, Any]]:
    """Run the source from `since`, and return what it printed, its `end` line last."""
    ran = invoke(
        cli.main,
        ["feed", "--store", str(store_dir), "--namespace", NAMESPACE, *options],
        stdin=f'{{"since": {since}}}',
    )
    assert ran.exit_code == 0, ran.stderr
    return [json.loads(line) for line in ran.stdout.splitlines()]


def test_it_pages_the_feed_past_its_cursor_and_ends_with_where_to_read_from(store: Store, store_dir: Path) -> None:
    artifact = publish(store)
    made = [seq(store.comment(artifact, None, f"Comment {n}.")) for n in range(5)]
    with mock.patch.object(cli, "MAX_FEED", 2):
        *changes, end = feed(store_dir)
    assert [c["seq"] for c in changes] == made, "every page is read before the end line"
    assert end == {"kind": "end", "through": made[-1]}
    assert feed(store_dir, made[-1]) == [end]


def test_a_run_past_its_most_stops_and_the_next_reads_on_missing_none_and_repeating_none(
    store: Store,
    store_dir: Path,
) -> None:
    ours, theirs = publish(store), publish(store, "PROJ-2")
    wanted: list[int] = []
    seen: list[int] = []
    since = 0
    for round_ in range(4):
        for _ in range(round_ + 1):
            wanted.append(seq(store.comment(ours, None, "ours")))
            store.comment(theirs, None, "theirs")
        *changes, end = feed(store_dir, since, "--origin", "canopy.ticket=PROJ-1", "--most", "2")
        seen.extend(c["seq"] for c in changes)
        assert all(c["origin"] == {"canopy.ticket": "PROJ-1"} for c in changes)
        since = end["through"]
    while True:
        *changes, end = feed(store_dir, since, "--origin", "canopy.ticket=PROJ-1", "--most", "2")
        seen.extend(c["seq"] for c in changes)
        if end["through"] == since:
            break
        since = end["through"]
    assert seen == wanted


@pytest.mark.parametrize("request_", ["[]", '{"since": -1}', '{"since": "4"}', '{"since": true}', "not json"])
def test_a_request_it_cannot_read_prints_nothing(store_dir: Path, request_: str) -> None:
    ran = invoke(cli.main, ["feed", "--store", str(store_dir)], stdin=request_)
    assert ran.exit_code == 2
    assert ran.stdout == ""


def test_it_reads_and_never_writes(store: Store, store_dir: Path) -> None:
    artifact = publish(store)
    store.comment(artifact, None, "Hm.")
    before = (store_dir / "artifacts.db").read_bytes()
    feed(store_dir)
    assert (store_dir / "artifacts.db").read_bytes() == before


# What canopy records of it


def test_canopy_records_every_change_it_prints(store: Store, store_dir: Path, canopy_env: CanopyEnv) -> None:
    artifact = publish(store)
    made = store.comment(artifact, Anchor.of("shard it", "We should "), "Why shard?")
    reply = store.reply(str(made["thread_id"]), "Contention.")
    publish(store, content=REWORDED, artifact_id=artifact)
    store.resolve(str(made["thread_id"]), resolved=True)
    conn = canopy_env.journal()
    source = Source(kind="artifacts", cmd=f"canopy-artifacts feed --store {store_dir} --namespace {NAMESPACE}")
    request = observe.Request(since=artifact_feed.cursor(conn, "artifacts"))

    found = artifact_feed.read(
        conn,
        config.load(canopy_env.root, canopy_env.user_file),
        InProcess(),
        source,
        request,
        name="artifacts",
        log=logs.for_tick(None),
    )

    assert (found.status, found.refused, found.missed) == (ConnectorRunStatus.OK, {}, None)
    assert found.recorded == {"comment_created": 2, "thread_resolved": 1}
    [thread] = records.fetch_all(
        conn,
        records.ObservedArtifactThread,
        sql.select("*").from_("observed_artifact_threads"),
    )
    assert (thread.id, thread.artifact_id, thread.ticket) == (made["thread_id"], artifact, "PROJ-1")
    assert (thread.exact, thread.state, thread.anchor_status) == (
        "shard it",
        ThreadState.RESOLVED,
        AnchorStatus.PASSAGE_GONE,
    )
    comments = records.fetch_all(
        conn,
        records.ObservedArtifactComment,
        sql.select("*").from_("observed_artifact_comments").order_by("seq"),
    )
    assert [(c.id, c.body, c.author, c.author_kind) for c in comments] == [
        (made["comment_id"], "Why shard?", "agent:implement", AuthorKind.AGENT),
        (reply["comment_id"], "Contention.", "agent:implement", AuthorKind.AGENT),
    ]
    assert artifact_feed.cursor(conn, "artifacts") == 3


@dataclass(frozen=True)
class InProcess:
    """A runner that runs `canopy-artifacts` in this process, as canopy would run it."""

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
        assert args[0] == "canopy-artifacts"
        result = invoke(cli.main, args[1:], stdin=stdin or "")
        for line in result.stdout.splitlines(keepends=True):
            if on_line is not None:
                on_line(line)
        return procs.Result(tuple(args), result.exit_code, result.stdout, result.stderr)

    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int:
        raise AssertionError(f"a connector is run, never spawned: {args}, {cwd}, {log_path}")
