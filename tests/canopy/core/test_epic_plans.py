"""An epic's plan, approved by the operator alone; replies asking for the next; members registered (§43)."""

from pathlib import Path
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import conversation, epics, plans
from canopy.core.vocab import PlanStatus
from canopy.infra import logs
from canopy.runs import epic_starts
from tests.canopy.helpers import epic_planned, in_tick, inline_context, operator, present
from tests.conftest import CanopyEnv, GitPool

PLAN = """\
# Epic: sessions

## Goal

Sessions survive a restart.

## Requirements

- **R1.** Sessions survive a restart of the API.
- **R2.** The web app reads the new store.

## Contracts

- **C1.** The store's read interface. Provided by B1; used by B2.

## Breakdown

### B1. Move the store

- Covers: R1
- Provides: C1
- Uses: none
- Repositories: repo
- After: none
- Trivial: no

### B2. Read from it

- Covers: R2
- Provides: none
- Uses: C1
- Repositories: repo
- After: B1
- Trivial: no

## Decisions

## Out of scope
"""


@pytest.fixture
def planned(canopy_env: CanopyEnv, git_pool: GitPool) -> CanopyEnv:
    """A workspace whose epic:1 has a plan waiting on the operator, `PLAN`."""
    assert git_pool.slots
    assert operator("epic", "submit", "Move sessions to the new store.") == 0
    epic_planned(canopy_env, PLAN)
    return canopy_env


def plan_file(env: CanopyEnv) -> Path:
    ctx = inline_context(env)
    return epics.plan_path(ctx.state_dir, 1, present(epics.current_plan(ctx.conn, 1)).run_id)


def test_the_operator_approves_the_plan_as_its_file_stands(
    capsys: pytest.CaptureFixture[str],
    planned: CanopyEnv,
) -> None:
    """The approval records the file's hash, their edits included, and keeps a copy of what they approved."""
    path = plan_file(planned)
    edited = PLAN.replace("survive a restart of the API", "survive a restart of the API and a deploy")
    path.write_text(edited)
    assert operator("plan", "epic:1", "--approve") == 0
    assert "Approved epic:1's plan, written by run 1." in capsys.readouterr().out
    ctx = inline_context(planned)
    plan = present(epics.current_plan(ctx.conn, 1))
    assert (plan.status, plan.approved_channel) == (PlanStatus.APPROVED, "cli")
    assert epics.approved_path(ctx.state_dir, 1, 1, present(plan.approved_sha256)).read_text() == edited
    assert present(epics.approved_outline(ctx.conn, ctx.state_dir, 1)).requirements["R1"].endswith("deploy.")
    assert operator("plan", "epic:1", "--approve") == 1
    assert "plan refused (no_plan)" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("args", "said"),
    [
        (("--skip",), "an epic's plan takes --approve alone"),
        (("--approve", "--message", "ok"), "an epic's plan takes --approve alone"),
    ],
)
def test_an_epic_s_plan_takes_approve_alone(
    capsys: pytest.CaptureFixture[str],
    planned: CanopyEnv,
    args: tuple[str, ...],
    said: str,
) -> None:
    """Skipping, notes, and item choices are a ticket's plan's; an epic's is approved whole."""
    assert planned
    assert operator("plan", "epic:1", *args) == 2
    assert said in capsys.readouterr().err


def test_a_plan_whose_edits_break_its_ids_cannot_be_approved(
    capsys: pytest.CaptureFixture[str],
    planned: CanopyEnv,
) -> None:
    """An edit canopy cannot read in the outline's shape refuses the approval, saying where."""
    plan_file(planned).write_text(PLAN.replace("- Covers: R2", "- Covers: R9"))
    assert operator("plan", "epic:1", "--approve") == 1
    assert "plan refused (bad_outline): epic:1's plan cannot be read: B2's Covers names R9" in capsys.readouterr().err


def test_only_the_operator_approves_or_replies(planned: CanopyEnv) -> None:
    """Inside a tick or a run, an approval and a reply are refused (TRUST_MODEL T1)."""
    with mock.patch.dict("os.environ", {"CANOPY_RUN_ID": "7"}):
        assert main(["plan", "epic:1", "--approve"]) == 1
        assert main(["reply", "epic:1", "Add a third requirement."]) == 1
    ctx = inline_context(planned)
    assert present(epics.current_plan(ctx.conn, 1)).status is PlanStatus.PROPOSED
    assert epics.messages_of(ctx.conn, 1) == []


def test_a_reply_asks_for_the_next_plan_which_reads_it_and_a_change_is_named(
    capsys: pytest.CaptureFixture[str],
    planned: CanopyEnv,
    agent_log: Path,
) -> None:
    """A reply starts the next plan run with the reply in its prompt; approving it names the ids it changed."""
    assert operator("plan", "epic:1", "--approve") == 0
    assert operator("reply", "epic:1", "Sessions expire after a day, too.") == 0
    assert "The next tick starts its next plan run, which reads your reply." in capsys.readouterr().out
    second = PLAN.replace(
        "- **R2.** The web app reads the new store.\n",
        "- **R2.** The web app reads the new store.\n- **R3.** Sessions expire after a day.\n",
    ).replace("- Covers: R2", "- Covers: R2, R3")
    epic_planned(planned, second)
    assert "Sessions expire after a day, too." in agent_log.read_text().splitlines()[-1]
    assert operator("plan", "epic:1", "--approve") == 0
    out = capsys.readouterr().out
    assert "  added: R3\n" in out
    assert "  changed: B2\n" in out
    ctx = inline_context(planned)
    assert [p.status for p in epics.plans_of(ctx.conn, 1)] == [PlanStatus.SUPERSEDED, PlanStatus.APPROVED]


def test_an_id_an_earlier_approval_dropped_is_never_approved_again(
    capsys: pytest.CaptureFixture[str],
    planned: CanopyEnv,
) -> None:
    """Once an approved plan drops an id, a later plan that uses it again cannot be approved (DESIGN §43)."""
    assert operator("plan", "epic:1", "--approve") == 0
    dropped = PLAN.replace("- **R2.** The web app reads the new store.\n", "").replace("- Covers: R2", "- Covers: R1")
    assert operator("reply", "epic:1", "Drop R2.") == 0
    epic_planned(planned, dropped)
    assert operator("plan", "epic:1", "--approve") == 0
    assert operator("reply", "epic:1", "Bring it back.") == 0
    epic_planned(planned, PLAN)
    assert operator("plan", "epic:1", "--approve") == 1
    assert (
        "plan refused (reused_id): the plan uses R2, which an earlier approved plan dropped" in capsys.readouterr().err
    )


def test_members_are_registered_against_the_approved_breakdown(
    capsys: pytest.CaptureFixture[str],
    planned: CanopyEnv,
) -> None:
    """Entries are checked against the approved plan; show lists each entry with its members or none yet."""
    assert operator("epic", "add", "epic:1", "PROJ-2", "--entry", "B1") == 1
    assert "epic add refused (no_plan)" in capsys.readouterr().err
    assert operator("plan", "epic:1", "--approve") == 0
    assert operator("epic", "add", "epic:1", "PROJ-2", "--entry", "B9") == 1
    assert "epic add refused (unknown_entry): the approved plan of epic:1 has no B9" in capsys.readouterr().err
    assert operator("epic", "add", "epic:1", "PROJ-2", "--entry", "B1") == 0
    assert operator("epic", "add", "epic:1", "PROJ-3", "--no-entry") == 0
    capsys.readouterr()
    assert operator("show", "epic:1") == 0
    shown = capsys.readouterr().out
    assert "  PROJ-2  B1  added" in shown
    assert "  PROJ-3  no entry  added" in shown
    assert "Breakdown of the approved plan (1 of 2 with no member yet):" in shown
    assert "  B1. Move the store  PROJ-2" in shown
    assert "  B2. Read from it  none yet" in shown
    # Registering again replaces its entries; adding without --entry leaves them.
    assert operator("epic", "add", "epic:1", "PROJ-2", "--entry", "B1", "--entry", "B2") == 0
    assert operator("epic", "add", "epic:1", "PROJ-2") == 0
    ctx = inline_context(planned)
    member = present(epics.membership(ctx.conn, "PROJ-2"))
    assert epics.entries_of(ctx.conn, member.id) == ["B1", "B2"]


def test_an_approval_refuses_while_a_plan_run_runs(planned: CanopyEnv) -> None:
    """The plan waiting is not approved while a newer one is being written."""
    ctx = inline_context(planned)
    assert operator("reply", "epic:1", "One more thing.") == 0
    with in_tick(ctx.conn) as tick_id:
        assert epic_starts.start_due(ctx, tick_id, logs.for_tick(tick_id))
    with pytest.raises(conversation.Refused, match="planning"):
        epics.approve(
            ctx.conn,
            ctx.state_dir,
            1,
            repos=frozenset({"repo"}),
            channel="cli",
            dispatch_lock=ctx.dispatch_lock_path,
        )


def test_an_approval_retried_after_its_copy_was_written_goes_through(planned: CanopyEnv) -> None:
    """A copy left by an approval that failed after writing it is found, not refused, when the same text is approved."""
    ctx = inline_context(planned)
    reading = plans.read(plan_file(planned))
    copy = epics.approved_path(ctx.state_dir, 1, 1, present(reading.sha256))
    copy.write_text(present(reading.text))
    assert operator("plan", "epic:1", "--approve") == 0
    assert present(epics.current_plan(ctx.conn, 1)).status is PlanStatus.APPROVED


def test_an_approved_copy_edited_after_is_refused_where_it_is_read(
    capsys: pytest.CaptureFixture[str],
    planned: CanopyEnv,
) -> None:
    """The kept copy is what the next approval is compared with: one no longer as approved is refused, not trusted."""
    assert operator("plan", "epic:1", "--approve") == 0
    ctx = inline_context(planned)
    plan = present(epics.current_plan(ctx.conn, 1))
    epics.approved_path(ctx.state_dir, 1, 1, present(plan.approved_sha256)).write_text(PLAN.replace("R1.", "R1:"))
    with pytest.raises(conversation.Refused, match="approved_changed"):
        epics.approved_outline(ctx.conn, ctx.state_dir, 1)
    assert operator("epic", "add", "epic:1", "PROJ-2", "--entry", "B1") == 1
    assert "epic add refused (approved_changed)" in capsys.readouterr().err


def test_entries_take_one_flag_and_only_the_operator_registers_them(
    capsys: pytest.CaptureFixture[str],
    planned: CanopyEnv,
) -> None:
    """--entry and --no-entry are each a registration of their own; inside a run either is refused (T1)."""
    assert operator("plan", "epic:1", "--approve") == 0
    assert operator("epic", "add", "epic:1", "PROJ-2", "--entry", "B1", "--no-entry") == 2
    assert "--entry names the entries each KEY fulfils, and --no-entry none; pass one" in capsys.readouterr().err
    with mock.patch.dict("os.environ", {"CANOPY_RUN_ID": "7"}):
        assert main(["epic", "add", "epic:1", "PROJ-2", "--entry", "B1"]) == 1
    assert "epic add refused (inside_run)" in capsys.readouterr().err
    assert epics.membership(inline_context(planned).conn, "PROJ-2") is None


def test_a_member_whose_entry_a_later_plan_dropped_is_named(
    capsys: pytest.CaptureFixture[str],
    planned: CanopyEnv,
) -> None:
    """A registration names the plan approved when it was made; show names one whose entry is gone since."""
    assert operator("plan", "epic:1", "--approve") == 0
    assert operator("epic", "add", "epic:1", "PROJ-3", "--entry", "B2") == 0
    dropped = PLAN.split("### B2.", maxsplit=1)[0] + "## Decisions\n\n## Out of scope\n"
    dropped = dropped.replace("- **R2.** The web app reads the new store.\n", "").replace(
        " Provided by B1; used by B2.",
        " Provided by B1.",
    )
    assert operator("reply", "epic:1", "Drop the web app's part.") == 0
    epic_planned(planned, dropped)
    assert operator("plan", "epic:1", "--approve") == 0
    capsys.readouterr()
    assert operator("show", "epic:1") == 0
    assert "Registered against entries the approved plan no longer holds: PROJ-3 (B2)" in capsys.readouterr().out
