"""What the runtime's record of every session holds, and what an index of it would cost (ROADMAP M72, stage 0)."""

import json
import os
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import pytest
from syrupy.assertion import SnapshotAssertion

from canopy.cli.main import main
from canopy.core import db, session_sizes
from canopy.core.session_sizes import Group, Sizes
from canopy.runtime.implementation import Version
from canopy.runtime.report import KeptSession
from tests.canopy.helpers import Kept, called, in_run, replied, runtime_database, runtime_record, sent, wrote
from tests.conftest import CanopyEnv, Journals, user_toml


@pytest.fixture
def data_home(tmp_path: Path) -> Iterator[Path]:
    """The operator's `$XDG_DATA_HOME`, where the runtime keeps its record."""
    home = tmp_path / "data"
    with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(home)}):
        yield home


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    """A workspace's state directory, where the trial indexes are built and removed."""
    found = tmp_path / "ws" / ".canopy"
    found.mkdir(parents=True)
    return found


@pytest.fixture
def journal(tmp_path: Path, journals: Journals) -> sqlite3.Connection:
    """A journal whose runs ran in `ses_overseer`, `ses_worker`, and `ses_plan`."""
    conn = journals.open(tmp_path / "canopy.db")
    with conn:
        journal_of_runs(conn)
    return conn


def journal_of_runs(conn: sqlite3.Connection) -> None:
    """A tick whose overseer ran in `ses_overseer`, and its worker and plan runs, in `ses_worker` and `ses_plan`."""
    started = "2026-11-10T09:00:00.000Z"
    db.touch_ticket(conn, "PROJ-1", "/work/ws")
    tick = conn.execute(
        "INSERT INTO ticks (started_at, ended_at, dry_run, status, session_id) VALUES (?, ?, 0, 'ok', 'ses_overseer')",
        (started, started),
    ).lastrowid
    conn.executemany(
        "INSERT INTO runs (tick_id, ticket_key, kind, branch, started_at, status, log_path, session_id) "
        "VALUES (?, 'PROJ-1', ?, 'b', ?, 'done', 'l', ?)",
        [(tick, "implement", started, "ses_worker"), (tick, "plan", started, "ses_plan")],
    )


def record_of_every_kind(state_dir: Path) -> None:
    """The runtime's record of the journal's runs' sessions, two subagents', a chore's trial, and the operator's own."""
    runtime_record(
        Kept("ses_overseer", "/work/ws", title="tick", messages=[sent("the state block"), replied(wrote("waiting"))]),
        Kept("ses_worker", "/slots/1", messages=[sent("implement the login form"), replied(wrote("pushed the login"))]),
        Kept(
            "ses_sub",
            "/slots/1",
            parent_id="ses_worker",
            messages=[replied(called("read", {"path": "login.py"}, "x"))],
        ),
        Kept("ses_subsub", "/slots/1", parent_id="ses_sub", messages=[replied(called("grep", {}, "def login(): ..."))]),
        Kept("ses_plan", "/slots/2", archived=True),
        Kept("ses_trial", str(state_dir / "chores" / "tidy")),
        Kept("ses_notes", "/home/me/notes", title="Login ideas", messages=[sent("how should it work")]),
        Kept("ses_reason", "/home/me/notes", messages=[replied({"type": "reasoning", "text": "login first"})]),
        Kept("ses_old", "/home/me/notes", archived=True),
        Kept("ses_web", "/work/web", messages=[("shell", {"command": "make", "output": {"output": "ok"}})]),
    )


def measured(conn: sqlite3.Connection, state_dir: Path, query: str = "") -> Sizes:
    found = session_sizes.measure(conn, version=Version.TWO, state_dir=state_dir, query=query)
    assert found.status == "found", found.error
    return found


def counts(groups: list[Group] | tuple[Group, ...]) -> dict[str, tuple[int, int, int]]:
    return {g.name: (g.sessions, g.subagents, g.archived) for g in groups if g.sessions or g.subagents}


def test_canopys_sessions_are_counted_by_kind_of_run_and_the_rest_by_directory(
    data_home: Path,
    state_dir: Path,
    journal: sqlite3.Connection,
) -> None:
    record_of_every_kind(state_dir)

    found = measured(journal, state_dir)

    # A subagent's counts with the nearest of canopy's sessions it ran for, however deep.
    assert counts(list(found.canopy)) == {
        "overseer": (1, 0, 0),
        "workers": (1, 2, 0),
        "plans": (1, 0, 1),
        "state_dir": (1, 0, 0),
    }
    assert [g.name for g in found.canopy] == list(session_sizes.OWNERS)
    assert counts(list(found.outside)) == {"/home/me/notes": (3, 0, 1), "/work/web": (1, 0, 0)}
    assert [g.name for g in found.outside] == ["/home/me/notes", "/work/web"]
    assert (found.databases, found.record_bytes) == (1, runtime_database().stat().st_size)


def test_the_text_is_counted_by_part_canopys_apart_from_the_rest(
    data_home: Path,
    state_dir: Path,
    journal: sqlite3.Connection,
) -> None:
    record_of_every_kind(state_dir)

    found = {t.part: t for t in measured(journal, state_dir).text}

    assert [t.part for t in measured(journal, state_dir).text] == [
        "title",
        "sent",
        "wrote",
        "reasoning",
        "given",
        "returned",
        "summary",
    ]
    sent_by_canopy = len("the state block") + len("implement the login form")
    assert (found["sent"].canopy_rows, found["sent"].canopy_chars) == (2, sent_by_canopy)
    assert (found["sent"].outside_rows, found["sent"].outside_chars) == (1, len("how should it work"))
    assert (found["title"].canopy_chars, found["title"].outside_chars) == (len("tick"), len("Login ideas"))
    assert (found["given"].canopy_chars, found["given"].outside_chars) == (len("login.py"), len("make"))
    assert found["summary"].canopy_rows + found["summary"].outside_rows == 0


def test_each_cut_is_indexed_with_and_without_positions_and_canopys_prompts_are_left_out(
    data_home: Path,
    state_dir: Path,
    journal: sqlite3.Connection,
) -> None:
    record_of_every_kind(state_dir)

    cuts = {c.cut: c for c in measured(journal, state_dir).cuts}

    # Said: two titles, the operator's prompt, and two replies' text; never canopy's two prompts. Did: two commands
    # and paths more. Read: one reasoning and three results more.
    assert (cuts["said"].rows, cuts["said"].parts) == (5, ["title", "sent", "wrote", "summary"])
    assert (cuts["did"].rows, cuts["read"].rows) == (7, 11)
    for cut in cuts.values():
        assert [i.positions for i in cut.indexes] == [True, False]
        assert all(i.size_bytes > 0 and i.found is None for i in cut.indexes)
        assert cut.scan is None
    assert not list(state_dir.iterdir()), "the trial indexes are removed when they are measured"


def test_the_words_are_found_in_each_cuts_index_and_by_a_plain_scan(
    data_home: Path,
    state_dir: Path,
    journal: sqlite3.Connection,
) -> None:
    record_of_every_kind(state_dir)

    found = measured(journal, state_dir, query="Login, please")

    assert found.words == ["Login", "please"]
    assert all(i.found is not None and i.found.sessions == 0 for c in found.cuts for i in c.indexes)
    cuts = {c.cut: c for c in measured(journal, state_dir, query="login").cuts}
    # Said: the worker's reply and the operator's title, never the worker's prompt. Did: the subagent's path too. Read:
    # what the deeper subagent's call returned, and the operator's reasoning.
    for cut, sessions in (("said", 2), ("did", 3), ("read", 5)):
        indexed = [i.found.sessions for i in cuts[cut].indexes if i.found is not None]
        scanned = cuts[cut].scan
        assert (indexed, scanned.sessions if scanned else None) == ([sessions, sessions], sessions), cut


def test_a_subagent_is_canopys_by_its_nearest_parent_and_a_loop_of_parents_is_no_ones(
    state_dir: Path,
    journal: sqlite3.Connection,
) -> None:
    kept = [
        KeptSession("ses_a", "ses_b", "/x", archived=False),
        KeptSession("ses_b", "ses_a", "/x", archived=False),
        KeptSession("ses_deep", "ses_mid", "/x", archived=False),
        KeptSession("ses_mid", "ses_overseer", "/x", archived=False),
        KeptSession("ses_lost", "ses_gone", "/x", archived=False),
    ]

    assert session_sizes.owners_of(journal, kept, state_dir) == {
        "ses_a": None,
        "ses_b": None,
        "ses_deep": "overseer",
        "ses_mid": "overseer",
        "ses_overseer": "overseer",
        "ses_lost": None,
        "ses_gone": None,
    }


def test_the_directories_past_the_first_are_counted_together(
    data_home: Path,
    state_dir: Path,
    journal: sqlite3.Connection,
) -> None:
    runtime_record(Kept("ses_1", "/a"), Kept("ses_2", "/a"), Kept("ses_3", "/b"), Kept("ses_4", "/c", archived=True))

    with mock.patch.object(session_sizes, "DIRECTORIES", 1):
        found = measured(journal, state_dir)

    assert counts(list(found.outside)) == {"/a": (2, 0, 0), session_sizes.OTHER_DIRECTORIES: (2, 0, 1)}


def test_a_record_that_is_missing_or_cannot_be_read_measures_nothing(
    data_home: Path,
    state_dir: Path,
    journal: sqlite3.Connection,
) -> None:
    assert session_sizes.measure(journal, version=Version.TWO, state_dir=state_dir).status == "missing"
    runtime_database().parent.mkdir(parents=True)
    runtime_database().write_text("not a database")

    found = session_sizes.measure(journal, version=Version.TWO, state_dir=state_dir)

    assert (found.status, found.cuts) == ("failed", ())
    unsupported = session_sizes.measure(journal, version=Version.ONE, state_dir=state_dir)
    assert unsupported.status == "unsupported"
    assert unsupported.error is not None
    assert "deprecated" in unsupported.error


def test_canopy_sessions_sizes_prints_the_measurement(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    canopy_env.write_user(user_toml(Version.TWO))  # Only OpenCode 2's record is measured.
    journal_of_runs(canopy_env.journal())
    record_of_every_kind(canopy_env.state_dir)

    assert main(["sessions", "--sizes", "login"]) == 0

    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("The runtime's record: 1 database, ")
    assert out[2].split() == ["canopy's", "sessions", "sessions", "subagents", "archived"]
    assert out[3].split() == ["overseer", "runs", "1", "0", "0"]
    assert out[4].split() == ["worker", "runs", "1", "2", "0"]
    start = out.index("Searched for login: how long it took, and in how many sessions a part held every word.")
    assert out[start + 1] == "said (title, sent, wrote, summary): 56 characters in 5 rows"
    assert re.fullmatch(r"  with positions +\S+ +\S+ +\S+ +2", out[start + 2])
    assert re.fullmatch(r"  without +\S+ +\S+ +\S+ +2", out[start + 3])
    assert re.fullmatch(r"  plain scan, no index +\S+ +2", out[start + 4])


def test_canopy_sessions_sizes_json_is_the_measurement(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
    snapshot: SnapshotAssertion,
) -> None:
    canopy_env.write_user(user_toml(Version.TWO))
    journal_of_runs(canopy_env.journal())
    record_of_every_kind(canopy_env.state_dir)

    assert main(["sessions", "--sizes", "--json", "login"]) == 0

    found = json.loads(capsys.readouterr().out)
    # Sizes and times are SQLite's and the machine's: their place is held, not their value.
    for key in ("record_bytes", "sqlite_version", "contentless_delete"):
        found[key] = f"<{key}>"
    for cut in found["cuts"]:
        cut["scan"]["seconds"] = "<seconds>"
        for index in cut["indexes"]:
            index["size_bytes"] = index["build_seconds"] = index["found"]["seconds"] = "<measured>"
    assert found == snapshot


def test_canopy_sessions_sizes_is_refused_inside_a_run(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with in_run(7):
        assert main(["sessions", "--sizes"]) == 1
    assert "sessions refused (inside_run): CANOPY_RUN_ID is set" in capsys.readouterr().err


@pytest.mark.opencode1  # OpenCode 1's record is not measured
def test_canopy_sessions_sizes_says_opencode_1s_record_is_not_measured(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime_record(Kept("ses_1", "/work"))

    assert main(["sessions", "--sizes"]) == 1

    assert "runtime.version 1 is deprecated, and its sessions' text has no reader" in capsys.readouterr().err


def test_words_no_session_holds_are_found_in_none(
    data_home: Path,
    state_dir: Path,
    journal: sqlite3.Connection,
) -> None:
    runtime_record(Kept("ses_1", "/a", title="hello"))

    cut = measured(journal, state_dir, query="absent").cuts[0]

    assert [i.found.sessions if i.found else None for i in cut.indexes] == [0, 0]
    assert cut.scan is not None
    assert cut.scan.sessions == 0
