"""Epics as the operator's subject (DESIGN §43): submitting one, its members, and the guards on both."""

import io
import sqlite3
import sys
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import config, conversation, db, epics, records
from canopy.core.context import Context
from tests.canopy.conftest import Ws
from tests.canopy.helpers import operator, present
from tests.conftest import CanopyEnv

TEXT = "Move sessions to the new store, across the API and the web app."


def submit(*args: str, code: int = 0) -> None:
    assert operator("epic", "submit", *args) == code


def members(conn: sqlite3.Connection, epic_id: int = 1) -> list[str]:
    return [m.ticket_key for m in epics.members_of(conn, epic_id)]


# Submitting


@pytest.mark.usefixtures("canopy_env")
def test_an_epic_is_submitted_listed_and_shown(
    capsys: pytest.CaptureFixture[str],
    conn: sqlite3.Connection,
) -> None:
    """A submission records the operator's text, its repository, project, and tracker epic, and the commands show it."""
    submit(TEXT, "--project", "PROJ", "--tracker-epic", "PROJ-1")
    [found] = epics.every(conn)
    assert (found.text, found.project, found.tracker_epic, found.channel) == (TEXT, "PROJ", "PROJ-1", "cli")
    assert epics.repos_of(conn, found.id) == ["repo"]
    assert "Submitted epic:1, over repo." in capsys.readouterr().out
    assert operator("epic", "list") == 0
    assert "epic:1  0 members" in capsys.readouterr().out
    assert operator("show", "epic:1") == 0
    shown = capsys.readouterr().out
    assert "  project PROJ" in shown
    assert "  tracker epic PROJ-1: its tickets are suggestions, none a member until you add it" in shown
    assert f"    {TEXT}" in shown
    assert "Members (0 of at most 8):" in shown


@pytest.mark.usefixtures("canopy_env")
def test_a_dash_reads_the_text_from_stdin(conn: sqlite3.Connection) -> None:
    """TEXT `-` reads the goal from stdin."""
    with mock.patch.object(sys, "stdin", io.StringIO(f"{TEXT}\n")):
        submit("-")
    assert [i.text for i in epics.every(conn)] == [TEXT]


@pytest.mark.usefixtures("canopy_env")
@pytest.mark.parametrize(
    ("args", "said"),
    [
        (("   ",), "epic submit refused (bad_body): the epic's text is empty"),
        (("x" * (epics.MAX_TEXT + 1),), "epic submit refused (bad_body)"),
        ((TEXT, "--repo", "web"), "epic submit refused (unknown_repo): 'web' is not a repository"),
        ((TEXT, "--project", "a b"), "epic submit refused (bad_key): 'a b' is not --project"),
        ((TEXT, "--tracker-epic", "PROJ 1"), "epic submit refused (bad_key): 'PROJ 1' is not --tracker-epic"),
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
    assert epics.every(conn) == []


def test_a_workspace_of_several_repositories_names_each_its_plan_reads(
    capsys: pytest.CaptureFixture[str],
    ws: Ws,
) -> None:
    """In a workspace of several repositories, `--repo` names each, once, in the order given."""
    submit(TEXT, code=1)
    assert "epic submit refused (unknown_repo): --repo is required" in capsys.readouterr().err
    submit(TEXT, "--repo", "web", "--repo", "api", "--repo", "web")
    assert epics.repos_of(ws.journal(), 1) == ["web", "api"]


def test_a_submission_id_records_one_epic_for_its_channel(ctx: Context) -> None:
    """The same submission id from the same channel finds its epic; from another, or with none, it is a new one."""

    def submitted(channel: str, submission: str | None) -> int:
        found = epics.submit(
            ctx.conn,
            ctx.workspace,
            TEXT,
            repos=(),
            project=None,
            tracker_epic=None,
            channel=channel,
            submission=submission,
        )
        return found.id

    assert [submitted("web", "form-0001"), submitted("web", "form-0001")] == [1, 1]
    assert [submitted("cli", "form-0001"), submitted("cli", None), submitted("cli", None)] == [2, 3, 4]
    with pytest.raises(conversation.Refused, match="bad_submission"):
        submitted("web", "no spaces")
    assert len(epics.every(ctx.conn)) == 4


@pytest.mark.parametrize("variable", ["CANOPY_RUN_ID", "CANOPY_TICK_ID"])
def test_a_submission_or_a_change_of_members_inside_a_run_or_a_tick_is_refused(
    capsys: pytest.CaptureFixture[str],
    ctx: Context,
    variable: str,
) -> None:
    """Only the operator submits an epic, says which tickets are its members, or stops it (TRUST_MODEL T1)."""
    submit(TEXT)
    assert operator("epic", "add", "epic:1", "PROJ-2") == 0
    with mock.patch.dict("os.environ", {variable: "7"}):
        assert main(["epic", "submit", "file tickets everywhere"]) == 1
        assert main(["epic", "add", "epic:1", "PROJ-3"]) == 1
        assert main(["epic", "remove", "epic:1", "PROJ-2"]) == 1
        assert main(["stop", "epic:1"]) == 1
        with pytest.raises(conversation.Refused, match="inside_run"):
            epics.stop(ctx.conn, 1)
        with pytest.raises(conversation.Refused, match="inside_run"):
            epics.submit(ctx.conn, ctx.workspace, TEXT, repos=(), project=None, tracker_epic=None, channel="cli")
        with pytest.raises(conversation.Refused, match="inside_run"):
            epics.add(ctx.conn, 1, ["PROJ-3"], bound=8, channel="cli")
        with pytest.raises(conversation.Refused, match="inside_run"):
            epics.remove(ctx.conn, 1, ["PROJ-2"], channel="cli")
    err = capsys.readouterr().err
    for verb in ("submit", "add", "remove"):
        assert f"epic {verb} refused (inside_run)" in err
    assert "stop refused (inside_run)" in err
    assert [e.stopped_at for e in epics.every(ctx.conn)] == [None]
    assert members(ctx.conn) == ["PROJ-2"]


# Members


@pytest.mark.usefixtures("canopy_env")
def test_members_are_added_once_and_shown(capsys: pytest.CaptureFixture[str], conn: sqlite3.Connection) -> None:
    """Adding makes each ticket a member once, and the epic and the ticket each show it."""
    submit(TEXT)
    assert operator("epic", "add", "epic:1", "PROJ-2", "PROJ-3", "PROJ-2") == 0
    assert "Added PROJ-2, PROJ-3 to epic:1." in capsys.readouterr().out
    assert operator("epic", "add", "epic:1", "PROJ-3", "PROJ-4") == 0
    out = capsys.readouterr().out
    assert "Added PROJ-4 to epic:1." in out
    assert "Already members: PROJ-3." in out
    assert members(conn) == ["PROJ-2", "PROJ-3", "PROJ-4"]
    assert operator("show", "epic:1") == 0
    assert "Members (3 of at most 8):\n  PROJ-2  no entry  added" in capsys.readouterr().out
    db.touch_ticket(conn, "PROJ-2", "repo")
    assert operator("show", "PROJ-2") == 0
    assert "  member of epic:1" in capsys.readouterr().out


@pytest.mark.usefixtures("canopy_env")
@pytest.mark.parametrize(
    ("args", "said"),
    [
        (("epic:9", "PROJ-5"), "epic add refused (unknown_epic): canopy has no epic:9"),
        (("task:1", "PROJ-5"), "epic add refused (bad_ref): task:1 is a task"),
        (("epic:1", "PROJ-5", "a b"), "epic add refused (bad_key): 'a b' is not a ticket key"),
        (("epic:2", "PROJ-5", "PROJ-2"), "epic add refused (other_epic): PROJ-2 is a member of epic:1"),
    ],
)
def test_an_addition_canopy_refuses_adds_none_of_its_keys(
    capsys: pytest.CaptureFixture[str],
    conn: sqlite3.Connection,
    args: tuple[str, ...],
    said: str,
) -> None:
    """A refused addition leaves every epic's members as they were: a ticket is a member of one at most."""
    submit(TEXT)
    submit("Another one.")
    assert operator("epic", "add", "epic:1", "PROJ-2") == 0
    assert operator("epic", "add", *args) == 1
    assert said in capsys.readouterr().err
    assert (members(conn, 1), members(conn, 2)) == (["PROJ-2"], [])


def test_max_epic_tickets_bounds_the_members(capsys: pytest.CaptureFixture[str], canopy_env: CanopyEnv) -> None:
    """Past `policy.max_epic_tickets`, an addition is refused whole, and a removal makes room again."""
    canopy_env.configure(canopy_env.user_file, {"policy": {"max_epic_tickets": 2}})
    conn = canopy_env.journal()
    submit(TEXT)
    assert operator("epic", "add", "epic:1", "PROJ-2") == 0
    assert operator("epic", "add", "epic:1", "PROJ-3", "PROJ-4") == 1
    said = "epic add refused (epic_full): epic:1 has 1 members, and policy.max_epic_tickets lets it "
    assert said in capsys.readouterr().err
    assert operator("epic", "add", "epic:1", "PROJ-3") == 0
    assert operator("epic", "remove", "epic:1", "PROJ-2") == 0
    assert operator("epic", "add", "epic:1", "PROJ-4") == 0
    assert members(conn) == ["PROJ-3", "PROJ-4"]


def test_a_lowered_bound_refuses_new_members_but_not_an_existing_one(
    capsys: pytest.CaptureFixture[str],
    canopy_env: CanopyEnv,
) -> None:
    """Below its members, a lowered bound refuses an addition, and leaves a key already a member as it is."""
    conn = canopy_env.journal()
    submit(TEXT)
    assert operator("epic", "add", "epic:1", "PROJ-2", "PROJ-3") == 0
    canopy_env.configure(canopy_env.user_file, {"policy": {"max_epic_tickets": 1}})
    assert operator("epic", "add", "epic:1", "PROJ-3") == 0
    assert "Already members: PROJ-3." in capsys.readouterr().out
    assert operator("epic", "add", "epic:1", "PROJ-3", "PROJ-4") == 1
    assert "epic add refused (epic_full)" in capsys.readouterr().err
    assert members(conn) == ["PROJ-2", "PROJ-3"]


def test_a_workspace_file_may_lower_max_epic_tickets_but_not_raise_it(canopy_env: CanopyEnv) -> None:
    """The bound is a guard a shared file may only tighten (TRUST_MODEL T7)."""
    canopy_env.configure(canopy_env.shared_file, {"policy": {"max_epic_tickets": 30}})
    assert config.load(canopy_env.root, canopy_env.user_file).policy.max_epic_tickets == 8
    canopy_env.configure(canopy_env.shared_file, {"policy": {"max_epic_tickets": 3}})
    assert config.load(canopy_env.root, canopy_env.user_file).policy.max_epic_tickets == 3


@pytest.mark.usefixtures("canopy_env")
def test_a_removal_ends_the_membership_and_keeps_its_row(
    capsys: pytest.CaptureFixture[str],
    conn: sqlite3.Connection,
) -> None:
    """A removed ticket may join another epic, and what it was a member of stays to read."""
    submit(TEXT)
    submit("Another one.")
    assert operator("epic", "add", "epic:1", "PROJ-2", "PROJ-3") == 0
    assert operator("epic", "remove", "epic:1", "PROJ-3", "PROJ-9") == 1
    assert "epic remove refused (not_member): PROJ-9 is not a member of epic:1" in capsys.readouterr().err
    assert members(conn) == ["PROJ-2", "PROJ-3"]
    assert operator("epic", "remove", "epic:1", "PROJ-3") == 0
    assert "Removed PROJ-3 from epic:1." in capsys.readouterr().out
    assert members(conn) == ["PROJ-2"]
    assert operator("epic", "add", "epic:2", "PROJ-3") == 0
    rows = records.select(records.EpicMember).where("ticket_key = 'PROJ-3'").order_by("id").all(conn)
    assert [(r.epic_id, r.removed_channel) for r in rows] == [(1, "cli"), (2, None)]
    assert present(epics.membership(conn, "PROJ-3")).epic_id == 2


# Stopping


@pytest.mark.usefixtures("canopy_env")
def test_a_stopped_epic_keeps_its_members_and_refuses_a_reply(
    capsys: pytest.CaptureFixture[str],
    conn: sqlite3.Connection,
) -> None:
    """A stop marks the epic once, leaves its members alone, and a reply, which asks for a plan, is refused."""
    submit(TEXT)
    assert operator("epic", "add", "epic:1", "PROJ-2") == 0
    assert operator("stop", "epic:1") == 0
    assert (
        "epic:1 is stopped; no plan run of it starts again. Its members are left as they are."
        in capsys.readouterr().out
    )
    stopped_at = present(epics.get(conn, 1)).stopped_at
    assert stopped_at is not None
    assert members(conn) == ["PROJ-2"]
    # Stopping it again changes nothing, and says so.
    assert operator("stop", "epic:1") == 0
    assert "epic:1 was already stopped." in capsys.readouterr().out
    assert present(epics.get(conn, 1)).stopped_at == stopped_at
    assert operator("reply", "epic:1", "Plan it after all.") == 1
    assert "reply refused (stopped)" in capsys.readouterr().err
    assert epics.messages_of(conn, 1) == []
    assert operator("epic", "list") == 0
    assert "epic:1  1 members  stopped" in capsys.readouterr().out
    assert operator("show", "epic:1") == 0
    shown = capsys.readouterr().out
    assert "ago: no plan run of it starts again" in shown
    assert "Plan runs (0 of at most 3):\n  none\n" in shown


@pytest.mark.usefixtures("canopy_env")
def test_stopping_an_epic_canopy_has_none_of_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    """`stop epic:N` names its guard when there is no such epic."""
    assert operator("stop", "epic:4") == 1
    assert "stop refused (unknown_epic): canopy has no epic:4" in capsys.readouterr().err
