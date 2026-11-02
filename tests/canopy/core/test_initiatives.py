"""Initiatives as the operator's subject (DESIGN §43): submitting one, its members, and the guards on both."""

import io
import sqlite3
import sys
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import config, conversation, db, initiatives, records
from canopy.core.context import Context
from tests.canopy.conftest import Ws
from tests.canopy.helpers import operator, present
from tests.conftest import CanopyEnv

TEXT = "Move sessions to the new store, across the API and the web app."


def submit(*args: str, code: int = 0) -> None:
    assert operator("initiative", "submit", *args) == code


def members(conn: sqlite3.Connection, initiative_id: int = 1) -> list[str]:
    return [m.ticket_key for m in initiatives.members_of(conn, initiative_id)]


# Submitting


@pytest.mark.usefixtures("canopy_env")
def test_an_initiative_is_submitted_listed_and_shown(
    capsys: pytest.CaptureFixture[str],
    conn: sqlite3.Connection,
) -> None:
    """A submission records the operator's text, its repository, project, and epic, and the commands show it."""
    submit(TEXT, "--project", "PROJ", "--epic", "PROJ-1")
    [found] = initiatives.every(conn)
    assert (found.text, found.project, found.epic, found.channel) == (TEXT, "PROJ", "PROJ-1", "cli")
    assert initiatives.repos_of(conn, found.id) == ["repo"]
    assert "Submitted init:1, over repo." in capsys.readouterr().out
    assert operator("initiative", "list") == 0
    assert "init:1  0 members" in capsys.readouterr().out
    assert operator("show", "init:1") == 0
    shown = capsys.readouterr().out
    assert "  project PROJ" in shown
    assert "  epic PROJ-1: its tickets are suggestions, none a member until you add it" in shown
    assert f"    {TEXT}" in shown
    assert "Members (0 of at most 8):" in shown


@pytest.mark.usefixtures("canopy_env")
def test_a_dash_reads_the_text_from_stdin(conn: sqlite3.Connection) -> None:
    """TEXT `-` reads the goal from stdin."""
    with mock.patch.object(sys, "stdin", io.StringIO(f"{TEXT}\n")):
        submit("-")
    assert [i.text for i in initiatives.every(conn)] == [TEXT]


@pytest.mark.usefixtures("canopy_env")
@pytest.mark.parametrize(
    ("args", "said"),
    [
        (("   ",), "initiative submit refused (bad_body): the initiative's text is empty"),
        (("x" * (initiatives.MAX_TEXT + 1),), "initiative submit refused (bad_body)"),
        ((TEXT, "--repo", "web"), "initiative submit refused (unknown_repo): 'web' is not a repository"),
        ((TEXT, "--project", "a b"), "initiative submit refused (bad_key): 'a b' is not --project"),
        ((TEXT, "--epic", "PROJ 1"), "initiative submit refused (bad_key): 'PROJ 1' is not --epic"),
    ],
)
def test_a_submission_canopy_cannot_use_is_refused(
    capsys: pytest.CaptureFixture[str],
    conn: sqlite3.Connection,
    args: tuple[str, ...],
    said: str,
) -> None:
    """A submission canopy cannot use records nothing."""
    submit(*args, code=1)
    assert said in capsys.readouterr().err
    assert initiatives.every(conn) == []


def test_a_workspace_of_several_repositories_names_each_its_plan_reads(
    capsys: pytest.CaptureFixture[str],
    ws: Ws,
) -> None:
    """In a workspace of several repositories, `--repo` names each, once, in the order given."""
    submit(TEXT, code=1)
    assert "initiative submit refused (unknown_repo): --repo is required" in capsys.readouterr().err
    submit(TEXT, "--repo", "web", "--repo", "api", "--repo", "web")
    assert initiatives.repos_of(ws.journal(), 1) == ["web", "api"]


@pytest.mark.parametrize("variable", ["CANOPY_RUN_ID", "CANOPY_TICK_ID"])
def test_a_submission_or_a_change_of_members_inside_a_run_or_a_tick_is_refused(
    capsys: pytest.CaptureFixture[str],
    ctx: Context,
    variable: str,
) -> None:
    """Only the operator submits an initiative or says which tickets are its members (TRUST_MODEL T1)."""
    submit(TEXT)
    assert operator("initiative", "add", "init:1", "PROJ-2") == 0
    with mock.patch.dict("os.environ", {variable: "7"}):
        assert main(["initiative", "submit", "file tickets everywhere"]) == 1
        assert main(["initiative", "add", "init:1", "PROJ-3"]) == 1
        assert main(["initiative", "remove", "init:1", "PROJ-2"]) == 1
        with pytest.raises(conversation.Refused, match="inside_run"):
            initiatives.submit(ctx.conn, ctx.workspace, TEXT, repos=(), project=None, epic=None, channel="cli")
        with pytest.raises(conversation.Refused, match="inside_run"):
            initiatives.add(ctx.conn, 1, ["PROJ-3"], bound=8, channel="cli")
        with pytest.raises(conversation.Refused, match="inside_run"):
            initiatives.remove(ctx.conn, 1, ["PROJ-2"], channel="cli")
    err = capsys.readouterr().err
    for verb in ("submit", "add", "remove"):
        assert f"initiative {verb} refused (inside_run)" in err
    assert len(initiatives.every(ctx.conn)) == 1
    assert members(ctx.conn) == ["PROJ-2"]


# Members


@pytest.mark.usefixtures("canopy_env")
def test_members_are_added_once_and_shown(capsys: pytest.CaptureFixture[str], conn: sqlite3.Connection) -> None:
    """Adding makes each ticket a member once, and the initiative and the ticket each show it."""
    submit(TEXT)
    assert operator("initiative", "add", "init:1", "PROJ-2", "PROJ-3", "PROJ-2") == 0
    assert "Added PROJ-2, PROJ-3 to init:1." in capsys.readouterr().out
    assert operator("initiative", "add", "init:1", "PROJ-3", "PROJ-4") == 0
    out = capsys.readouterr().out
    assert "Added PROJ-4 to init:1." in out
    assert "Already members: PROJ-3." in out
    assert members(conn) == ["PROJ-2", "PROJ-3", "PROJ-4"]
    assert operator("show", "init:1") == 0
    assert "Members (3 of at most 8):\n  PROJ-2  added" in capsys.readouterr().out
    db.touch_ticket(conn, "PROJ-2", "repo")
    assert operator("show", "PROJ-2") == 0
    assert "  member of init:1" in capsys.readouterr().out


@pytest.mark.usefixtures("canopy_env")
@pytest.mark.parametrize(
    ("args", "said"),
    [
        (("init:9", "PROJ-5"), "initiative add refused (unknown_initiative): canopy has no init:9"),
        (("task:1", "PROJ-5"), "initiative add refused (bad_ref): task:1 is a task"),
        (("init:1", "PROJ-5", "a b"), "initiative add refused (bad_key): 'a b' is not a ticket key"),
        (("init:2", "PROJ-5", "PROJ-2"), "initiative add refused (other_initiative): PROJ-2 is a member of init:1"),
    ],
)
def test_an_addition_canopy_refuses_adds_none_of_its_keys(
    capsys: pytest.CaptureFixture[str],
    conn: sqlite3.Connection,
    args: tuple[str, ...],
    said: str,
) -> None:
    """A refused addition leaves every initiative's members as they were: a ticket is a member of one at most."""
    submit(TEXT)
    submit("Another one.")
    assert operator("initiative", "add", "init:1", "PROJ-2") == 0
    assert operator("initiative", "add", *args) == 1
    assert said in capsys.readouterr().err
    assert (members(conn, 1), members(conn, 2)) == (["PROJ-2"], [])


def test_max_initiative_tickets_bounds_the_members(capsys: pytest.CaptureFixture[str], canopy_env: CanopyEnv) -> None:
    """Past `policy.max_initiative_tickets`, an addition is refused whole, and a removal makes room again."""
    canopy_env.configure(canopy_env.user_file, {"policy": {"max_initiative_tickets": 2}})
    conn = canopy_env.journal()
    submit(TEXT)
    assert operator("initiative", "add", "init:1", "PROJ-2") == 0
    assert operator("initiative", "add", "init:1", "PROJ-3", "PROJ-4") == 1
    said = "initiative add refused (initiative_full): init:1 has 1 members, and policy.max_initiative_tickets lets it "
    assert said in capsys.readouterr().err
    assert operator("initiative", "add", "init:1", "PROJ-3") == 0
    assert operator("initiative", "remove", "init:1", "PROJ-2") == 0
    assert operator("initiative", "add", "init:1", "PROJ-4") == 0
    assert members(conn) == ["PROJ-3", "PROJ-4"]


def test_a_workspace_file_may_lower_max_initiative_tickets_but_not_raise_it(canopy_env: CanopyEnv) -> None:
    """The bound is a guard a shared file may only tighten (TRUST_MODEL T7)."""
    canopy_env.configure(canopy_env.shared_file, {"policy": {"max_initiative_tickets": 30}})
    assert config.load(canopy_env.root, canopy_env.user_file).policy.max_initiative_tickets == 8
    canopy_env.configure(canopy_env.shared_file, {"policy": {"max_initiative_tickets": 3}})
    assert config.load(canopy_env.root, canopy_env.user_file).policy.max_initiative_tickets == 3


@pytest.mark.usefixtures("canopy_env")
def test_a_removal_ends_the_membership_and_keeps_its_row(
    capsys: pytest.CaptureFixture[str],
    conn: sqlite3.Connection,
) -> None:
    """A removed ticket may join another initiative, and what it was a member of stays to read."""
    submit(TEXT)
    submit("Another one.")
    assert operator("initiative", "add", "init:1", "PROJ-2", "PROJ-3") == 0
    assert operator("initiative", "remove", "init:1", "PROJ-3", "PROJ-9") == 1
    assert "initiative remove refused (not_member): PROJ-9 is not a member of init:1" in capsys.readouterr().err
    assert members(conn) == ["PROJ-2", "PROJ-3"]
    assert operator("initiative", "remove", "init:1", "PROJ-3") == 0
    assert "Removed PROJ-3 from init:1." in capsys.readouterr().out
    assert members(conn) == ["PROJ-2"]
    assert operator("initiative", "add", "init:2", "PROJ-3") == 0
    rows = records.select(records.InitiativeMember).where("ticket_key = 'PROJ-3'").order_by("id").all(conn)
    assert [(r.initiative_id, r.removed_channel) for r in rows] == [(1, "cli"), (2, None)]
    assert present(initiatives.membership(conn, "PROJ-3")).initiative_id == 2
