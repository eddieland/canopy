"""Every session the runtime keeps, listed and found by its title, as the journal records them."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

from canopy.cli import sessions as sessions_cli
from canopy.cli.main import main
from canopy.core import db, records, runtime_sessions, session_list
from canopy.core.session_list import MadeBy
from canopy.runtime.report import ModelUse, SessionPage, SessionSpend
from tests.canopy.helpers import in_run

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Sequence

    from canopy.core.session_list import Listed, Whose
    from tests.conftest import CanopyEnv

#: 2026-10-24T12:00:00Z, in milliseconds since the epoch.
NOON_MS: Final = 1_792_843_200_000
#: The workspace's state directory, below which every session is canopy's.
STATE_DIR: Final = Path("/work/.canopy")
#: A router: a model a provider serves by sending each request on to another, so no reply names it.
AUTO: Final = "github-copilot/auto"


def kept(
    session_id: str,
    title: str | None,
    *,
    minute: int = 0,
    parent: str | None = None,
    directory: str = "/home/me/notes",
    archived: bool = False,
    asked: str | None = None,
    served: Sequence[str] = (),
) -> SessionSpend:
    """A session as the runtime reports it to a read that keeps titles, started `minute` minutes after noon.

    `asked` is the model it was set to run on, and `served` the models its replies name, the most costly first.
    """
    at = NOON_MS + minute * 60_000
    return SessionSpend(
        session_id=session_id,
        parent_id=parent,
        directory=directory,
        created_ms=at,
        updated_ms=at,
        cost_usd=0.25,
        input=0,
        output=0,
        reasoning=0,
        cache_read=0,
        cache_write=0,
        title=title,
        archived_ms=at if archived else None,
        asked=asked,
        models=tuple(ModelUse(model, 1, 1.0 / (n + 1)) for n, model in enumerate(served)),
    )


def read(conn: sqlite3.Connection, *sessions: SessionSpend, exclude: Sequence[str] = ()) -> None:
    """Record `sessions` as the loop's read keeps them under `exclude`."""
    last = max(sessions, key=lambda s: (s.updated_ms, s.session_id))
    page = SessionPage("found", sessions, cursor=(last.updated_ms, last.session_id))
    runtime_sessions.record(conn, page, titles=runtime_sessions.titles_setting(exclude), restarted=True)


def listed(
    conn: sqlite3.Connection,
    whose: Whose = "outside",
    *,
    words: Sequence[str] = (),
    exclude: Sequence[str] = (),
    archived: bool = False,
    directory: str | None = None,
    limit: int = session_list.LISTED,
    model: str | None = None,
) -> list[Listed]:
    """The sessions a list holds."""
    return list(
        session_list.listing(
            conn,
            whose=whose,
            state_dir=STATE_DIR,
            exclude=exclude,
            words=words,
            archived=archived,
            directory=directory,
            limit=limit,
            model=model,
        ).sessions,
    )


def tree(sessions: Sequence[Listed]) -> list[object]:
    """Each session's id, with its subagents' under it."""
    return [(s.session_id, tree(s.subagents)) if s.subagents else s.session_id for s in sessions]


def ran_in(conn: sqlite3.Connection, session_id: str) -> int:
    """Record a tick whose overseer ran in session `session_id`, and return its id."""
    tick_id = db.start_tick(conn, dry_run=False)
    records.update(records.Tick).set(session_id=session_id).where("id = ?", tick_id).run(conn)
    return tick_id


def test_the_sessions_outside_canopy_are_listed_newest_first_each_subagents_under_it(conn: sqlite3.Connection) -> None:
    tick_id = ran_in(conn, "ses_tick")
    read(
        conn,
        kept("ses_old", "An old one", minute=1),
        kept("ses_new", "A new one", minute=5),
        kept("ses_sub", "Its subagent", minute=6, parent="ses_new"),
        kept("ses_subsub", "And its own", minute=7, parent="ses_sub"),
        kept("ses_tick", "Tick", minute=9, directory="/work"),
        kept("ses_tick_sub", "Explore", minute=10, parent="ses_tick", directory="/work"),
        kept("ses_chore", "Chore", minute=11, directory=str(STATE_DIR / "chores" / "lint")),
    )

    outside = listed(conn)
    canopys = listed(conn, "canopy")

    assert tree(outside) == [("ses_new", [("ses_sub", ["ses_subsub"])]), "ses_old"]
    assert [(s.title, s.directory, s.cost_usd) for s in outside] == [
        ("A new one", "/home/me/notes", 0.25),
        ("An old one", "/home/me/notes", 0.25),
    ]
    assert tree(canopys) == ["ses_chore", ("ses_tick", ["ses_tick_sub"])]
    assert [(s.made_by, [b.made_by for b in s.subagents]) for s in canopys] == [
        (None, []),
        (MadeBy("ticks", tick_id), [MadeBy("ticks", tick_id)]),
    ]


def test_words_find_the_newest_whose_title_holds_every_one_a_subagents_among_them(conn: sqlite3.Connection) -> None:
    read(
        conn,
        kept("ses_1", "Fix the FLAKY login test", minute=1),
        kept("ses_2", "Flaky deploy", minute=2),
        kept("ses_3", "The login page", minute=3),
        kept("ses_4", "Look into the flaky login", minute=4, parent="ses_3"),
        kept("ses_5", "100% of the logins", minute=5),
        kept("ses_6", None, minute=6),
    )

    assert [s.session_id for s in listed(conn, words=["flaky", "LOGIN"])] == ["ses_4", "ses_1"]
    assert [s.session_id for s in listed(conn, words=["0%"])] == ["ses_5"]
    assert [s.session_id for s in listed(conn, words=["_"])] == []
    assert [s.parent_id for s in listed(conn, words=["look"])] == ["ses_3"]


def test_a_session_names_the_model_it_was_asked_to_run_on_and_those_that_served_it(conn: sqlite3.Connection) -> None:
    run_id = ran_in(conn, "ses_tick")
    records.update(records.Tick).set(model="openai/gpt-5@high").where("id = ?", run_id).run(conn)
    read(
        conn,
        kept("ses_routed", "Routed", asked=AUTO, served=["github-copilot/gpt-5", "github-copilot/claude-x"]),
        kept("ses_plain", "Plain", minute=1, served=["openai/gpt-5"]),
        kept("ses_tick", "Tick", minute=2, directory="/work", served=["openai/gpt-5@high"]),
        # A subagent's model is not the one canopy asked for its run.
        kept("ses_sub", "Sub", minute=3, directory="/work", parent="ses_tick", served=["openai/gpt-5-mini"]),
    )

    assert [(s.session_id, s.asked, s.models) for s in listed(conn)] == [
        ("ses_plain", None, ("openai/gpt-5",)),
        ("ses_routed", AUTO, ("github-copilot/gpt-5", "github-copilot/claude-x")),
    ]
    [tick] = listed(conn, "canopy")
    assert (tick.asked, tick.models) == ("openai/gpt-5@high", ("openai/gpt-5@high",))
    [sub] = tick.subagents
    assert (sub.asked, sub.models) == (None, ("openai/gpt-5-mini",))


def test_a_list_narrowed_to_a_model_holds_the_sessions_asked_for_it_or_served_by_it(conn: sqlite3.Connection) -> None:
    run_id = ran_in(conn, "ses_tick")
    records.update(records.Tick).set(model=AUTO).where("id = ?", run_id).run(conn)
    read(
        conn,
        kept("ses_routed", "Routed", asked=AUTO, served=["github-copilot/gpt-5"]),
        kept("ses_direct", "Direct", minute=1, served=["github-copilot/gpt-5"]),
        kept("ses_other", "Other", minute=2, served=["openai/gpt-5"]),
        kept("ses_sub", "Sub", minute=3, parent="ses_routed", asked=AUTO),
        kept("ses_tick", "Tick", minute=4, directory="/work", served=["github-copilot/claude-x"]),
    )

    # Each on a line of its own, a subagent's among them, as a list found by words is.
    assert tree(listed(conn, model=AUTO)) == ["ses_sub", "ses_routed"]
    assert tree(listed(conn, model="github-copilot/gpt-5")) == ["ses_direct", "ses_routed"]
    assert tree(listed(conn, "canopy", model=AUTO)) == ["ses_tick"]
    assert listed(conn, model="github-copilot/nonesuch") == []


def test_a_session_in_an_excluded_directory_is_never_listed(conn: sqlite3.Connection) -> None:
    exclude = ["/home/me/clients/*"]
    read(
        conn,
        kept("ses_mine", "Mine", directory="/home/me/notes"),
        kept("ses_client", "A client's", directory="/home/me/clients/acme"),
        kept("ses_deep", "Deeper", directory="/home/me/clients/acme/api/src"),
        exclude=exclude,
    )

    assert [s.session_id for s in listed(conn, exclude=exclude)] == ["ses_mine"]
    assert [s.session_id for s in listed(conn, words=["a"], exclude=exclude)] == []
    client = runtime_sessions.of_session(conn, "ses_client")
    assert client is not None
    assert client.title is None


def test_a_list_narrowed_to_a_directory_holds_the_sessions_that_ran_in_that_one_alone(conn: sqlite3.Connection) -> None:
    exclude = ["/home/me/clients/*"]
    read(
        conn,
        kept("ses_infra", "Infra", minute=1, directory="/home/me/acme/infra"),
        kept("ses_sub", "Its subagent", minute=2, parent="ses_infra", directory="/home/me/acme/infra"),
        kept("ses_away", "Its subagent elsewhere", minute=3, parent="ses_infra", directory="/srv/scratch"),
        kept("ses_acme", "Above it", minute=4, directory="/home/me/acme"),
        kept("ses_below", "Below it", minute=5, directory="/home/me/acme/infra/modules"),
        kept("ses_client", "A client's", minute=6, directory="/home/me/clients/globex"),
        exclude=exclude,
    )

    assert tree(listed(conn, directory="/home/me/acme/infra", exclude=exclude)) == [("ses_infra", ["ses_sub"])]
    assert [s.session_id for s in listed(conn, words=["it"], directory="/home/me/acme", exclude=exclude)] == [
        "ses_acme",
    ]
    # Exactly the directory, never one below it nor a pattern.
    assert listed(conn, directory="/home/me/acme/*", exclude=exclude) == []


def test_a_list_narrowed_to_a_directory_holds_every_session_that_ran_there_however_deep(
    conn: sqlite3.Connection,
) -> None:
    """A subagent whose parent ran elsewhere heads a tree of its own, and one below it that ran here stays under it."""
    read(
        conn,
        kept("ses_root", "Elsewhere", minute=1, directory="/srv/scratch"),
        kept("ses_here", "Here, its parent elsewhere", minute=2, parent="ses_root", directory="/home/me/acme"),
        kept("ses_under", "Under it, here too", minute=3, parent="ses_here", directory="/home/me/acme"),
        kept("ses_away", "Under it, elsewhere", minute=4, parent="ses_here", directory="/srv/scratch"),
        kept("ses_deep", "Under that, here", minute=5, parent="ses_away", directory="/home/me/acme"),
    )

    assert tree(listed(conn, directory="/home/me/acme")) == ["ses_deep", ("ses_here", ["ses_under"])]
    assert tree(listed(conn, directory="/srv/scratch")) == ["ses_away", "ses_root"]


def test_a_list_narrowed_to_an_excluded_directory_holds_none_of_its_sessions(conn: sqlite3.Connection) -> None:
    """Read before the directory was excluded, its session is in the journal, and listed only until it is."""
    read(conn, kept("ses_client", "A client's", directory="/home/me/clients/globex"))

    assert [s.session_id for s in listed(conn, directory="/home/me/clients/globex")] == ["ses_client"]
    assert listed(conn, directory="/home/me/clients/globex", exclude=["/home/me/clients/*"]) == []


def test_an_archived_session_is_listed_only_when_asked_for(conn: sqlite3.Connection) -> None:
    read(conn, kept("ses_1", "Kept"), kept("ses_2", "Archived", minute=1, archived=True))

    assert [s.session_id for s in listed(conn)] == ["ses_1"]
    assert [(s.session_id, s.archived) for s in listed(conn, archived=True)] == [("ses_2", True), ("ses_1", False)]


def test_a_list_says_when_more_match_than_it_holds(conn: sqlite3.Connection) -> None:
    read(conn, *(kept(f"ses_{n}", f"Session {n}", minute=n) for n in range(3)))

    found = session_list.listing(conn, whose="outside", state_dir=STATE_DIR, exclude=(), limit=2)

    assert ([s.session_id for s in found.sessions], found.more) == (["ses_2", "ses_1"], True)


def test_a_list_says_how_far_the_read_has_come_and_whether_it_reads_titles_as_set(conn: sqlite3.Connection) -> None:
    before = session_list.progress(conn, ())
    read(conn, kept("ses_1", "One", minute=3), exclude=["/srv/scratch"])

    now = session_list.progress(conn, ["/srv/scratch"])
    changed = session_list.progress(conn, [])

    assert (before.read_at, before.current) == (None, False)
    assert (now.through, now.current, now.error) == ("2026-10-24T12:03:00.000Z", True, None)
    assert changed.current is False


def test_canopy_sessions_lists_none_while_search_is_off_and_is_refused_inside_a_run(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with canopy_env.journal() as conn:
        read(conn, kept("ses_1", "Mine"))

    assert main(["sessions"]) == 1
    assert sessions_cli.OFF in capsys.readouterr().err

    canopy_env.append_user("\n[sessions]\nsearch = 'titles'\n")
    with in_run(7):
        assert main(["sessions"]) == 1
    assert "sessions refused (inside_run): CANOPY_RUN_ID is set" in capsys.readouterr().err


def test_canopy_sessions_finds_one_of_the_operators_by_its_title_with_the_command_that_reopens_it(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    canopy_env.append_user("\n[sessions]\nsearch = 'titles'\nexclude = ['/home/me/clients']\n")
    with canopy_env.journal() as conn:
        tick_id = ran_in(conn, "ses_tick")
        read(
            conn,
            kept("ses_mine", "Draft the release notes", directory="/home/me/my notes"),
            kept("ses_other", "Sketch a parser", minute=1),
            kept("ses_client", "Release a client's app", minute=2, directory="/home/me/clients/acme"),
            kept("ses_tick", "Tick release", minute=3, directory="/work"),
            exclude=["/home/me/clients"],
        )

    assert main(["sessions", "release"]) == 0
    printed = capsys.readouterr().out
    assert main(["sessions", "--canopy", "--json"]) == 0
    canopys = json.loads(capsys.readouterr().out)

    assert "Sessions outside canopy whose title holds release, newest first:" in printed
    assert "Draft the release notes" in printed
    assert "cd '/home/me/my notes' && opencode --session ses_mine" in printed
    assert "parser" not in printed
    assert "client" not in printed
    assert "Read every session updated up to" in printed
    [tick] = canopys["sessions"]
    assert (tick["asked"], tick["models"]) == (None, [])
    assert (tick["title"], tick["made_by"], tick["reopen"]) == (
        "Tick release",
        {"table": "ticks", "run_id": tick_id},
        None,
    )
    assert canopys["progress"]["current"] is True


def test_canopy_sessions_names_each_sessions_model_and_narrows_the_list_to_one(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    canopy_env.append_user("\n[sessions]\nsearch = 'titles'\n")
    with canopy_env.journal() as conn:
        read(
            conn,
            kept("ses_routed", "Routed", asked=AUTO, served=["github-copilot/gpt-5"]),
            kept("ses_plain", "Plain", minute=1, served=["openai/gpt-5"]),
            kept("ses_unknown", "Unknown", minute=2),
        )

    assert main(["sessions"]) == 0
    every = capsys.readouterr().out
    assert main(["sessions", "--model", AUTO]) == 0
    routed = capsys.readouterr().out
    assert main(["sessions", "--model", AUTO, "--json"]) == 0
    [found] = json.loads(capsys.readouterr().out)["sessions"]

    assert f"    model {AUTO} -> github-copilot/gpt-5\n" in every
    assert "    model openai/gpt-5\n" in every
    assert every.count("    model ") == 2
    assert routed.startswith(f"Sessions outside canopy on {AUTO}, newest first:\n")
    assert "Routed" in routed
    assert "Plain" not in routed
    assert (found["session_id"], found["asked"], found["models"]) == ("ses_routed", AUTO, ["github-copilot/gpt-5"])


@pytest.mark.parametrize(
    ("asked", "served", "line"),
    [
        (
            AUTO,
            ["github-copilot/gpt-5", "github-copilot/claude-x"],
            f"model {AUTO} -> github-copilot/gpt-5, github-copilot/claude-x",
        ),
        # A session names a variant only when it is not the model's default.
        ("openai/gpt-5@medium", ["openai/gpt-5"], "model openai/gpt-5@medium"),
        ("openai/gpt-5", ["openai/gpt-5"], "model openai/gpt-5"),
        ("openai/gpt-5", [], "model openai/gpt-5"),
        (None, ["openai/gpt-5", "openai/gpt-5-mini"], "model openai/gpt-5, openai/gpt-5-mini"),
        (None, [], None),
    ],
)
def test_a_sessions_model_line_names_what_was_asked_and_what_served_only_when_they_differ(
    asked: str | None,
    served: list[str],
    line: str | None,
) -> None:
    assert sessions_cli.model_line(asked, served) == line
