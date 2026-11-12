"""An epic's attachments (DESIGN §22, §43): read by its plan runs, and by every run of each ticket that is its member.

A member's run finds its epic's copies in `.canopy-attachments/_epic/`, beside its ticket's own, and its prompt names
each in a group of their own; the epic's planner finds them at the top of its desk's `.canopy-attachments/`.
"""

from pathlib import Path

from canopy.cli.main import main
from canopy.core import contract, conversation, epics
from canopy.core.vocab import RunKind, RunStatus
from canopy.infra import logs
from canopy.runs import attachments, epic_runs, epic_starts
from tests.canopy.helpers import (
    BRANCH,
    EPIC_PLAN,
    KEY,
    InlineRunner,
    agent_runs,
    commands_run,
    commit_and_push,
    in_tick,
    inline_context,
    operator,
    planner_does,
    present,
    worker_does,
)
from tests.canopy.scenario_helpers import Scenario, dispatches
from tests.conftest import CanopyEnv, GitPool

SPEC = "# Sessions\n\nThe store keeps a session for 30 days.\n"
DOC = "# PROJ-1\n\nMove the reads first.\n"
EPIC_COPY = f"{attachments.RUN_DIR}/{attachments.EPIC_DIR}/spec.md"
OWN_COPY = f"{attachments.RUN_DIR}/design.md"
EPIC = conversation.Ref(conversation.EPIC, "1")


def attach(scenario: Scenario, ref: str, name: str, text: str) -> Path:
    """Attach `text` to `ref` as `name` through the CLI; returns where it is kept."""
    source = scenario.env.root / f"source-{name}"
    source.write_text(text)
    scenario.operator("attach", ref, str(source), "--name", name)
    [found] = [a for a in attachments.of(scenario.conn, conversation.parse_ref(ref)) if a.name == name]
    return attachments.path(scenario.env.state_dir, found)


def member_epic(scenario: Scenario) -> None:
    """Submit epic:1, with a spec attached, and make PROJ-1 its member; no plan is needed for its files to reach it."""
    assert operator("epic", "submit", "Move sessions to the new store.") == 0
    attach(scenario, "epic:1", "spec.md", SPEC)
    assert operator("epic", "add", "epic:1", KEY) == 0


def test_an_epic_takes_an_attachment_and_shows_it(scenario: Scenario) -> None:
    assert operator("epic", "submit", "Move sessions to the new store.") == 0
    kept = attach(scenario, "epic:1", "spec.md", SPEC)
    assert kept.read_text() == SPEC
    assert kept.parent.name == "epic.1"
    shown = scenario.operator("show", "epic:1").out
    assert "Attachments (1):\n  spec.md  51 bytes  attached" in shown
    assert "Removed spec.md from epic:1." in scenario.operator("detach", "epic:1", "spec.md").out
    assert attachments.of(scenario.conn, EPIC) == []


def test_an_unknown_or_stopped_epic_takes_no_attachment(scenario: Scenario, tmp_path: Path) -> None:
    source = tmp_path / "spec.md"
    source.write_text(SPEC)
    assert (
        "attach refused (unknown): canopy has no epic:1"
        in scenario.operator("attach", "epic:1", str(source), code=1).err
    )
    assert operator("epic", "submit", "Move sessions to the new store.") == 0
    assert operator("stop", "epic:1") == 0
    assert "attach refused (stopped)" in scenario.operator("attach", "epic:1", str(source), code=1).err


def test_a_members_implement_finds_its_epics_files_beside_its_own(scenario: Scenario, git_pool: GitPool) -> None:
    """The ticket's own copies and its epic's, each subject's under its limits, ignored by git, gone after."""
    assert git_pool.slots
    member_epic(scenario)
    scenario.seen()
    attach(scenario, KEY, "design.md", DOC)
    looks = [
        ["cat", EPIC_COPY],
        ["cat", OWN_COPY],
        ["git", "status", "--porcelain"],
        ["git", "check-ignore", EPIC_COPY],
    ]
    run = scenario.run(worker=worker_does(*looks, *commit_and_push(BRANCH)))
    assert run.status is RunStatus.DONE, Path(run.row["log_path"]).read_text()
    *_, (epic_cat, own_cat, status, ignored, *_) = commands_run(scenario.agent_log)
    assert (epic_cat["stdout"], own_cat["stdout"]) == (SPEC, DOC)
    assert status["stdout"] == ""
    assert ignored["returncode"] == 0
    slot = Path(str(agent_runs(scenario.agent_log)[-1]["cwd"]))
    assert f"- `{slot / OWN_COPY}` (32 bytes)" in run.prompt
    assert "Attached to `epic:1`, the epic this ticket is a member of" in run.prompt
    assert f"- `{slot / EPIC_COPY}` (51 bytes)" in run.prompt
    # Named, never quoted.
    assert "30 days" not in run.prompt
    assert not (slot / attachments.RUN_DIR).exists()


def test_a_members_planner_finds_its_epics_files_in_its_desk(scenario: Scenario, git_pool: GitPool) -> None:
    assert git_pool.slots
    member_epic(scenario)
    run = scenario.run(dispatches(kind=RunKind.PLAN), worker=planner_does(["cat", EPIC_COPY], plan="# Plan\n"))
    assert run.status is RunStatus.DONE, Path(run.row["log_path"]).read_text()
    cat = commands_run(scenario.agent_log)[-1][-1]
    assert cat["stdout"] == SPEC
    desk = Path(str(agent_runs(scenario.agent_log)[-1]["cwd"]))
    assert f"- `{desk / EPIC_COPY}` (51 bytes)" in run.prompt


def test_a_ticket_that_left_its_epic_gets_none_of_its_files(scenario: Scenario, git_pool: GitPool) -> None:
    assert git_pool.slots
    member_epic(scenario)
    assert operator("epic", "remove", "epic:1", KEY) == 0
    run = scenario.run(worker=worker_does(["test", "-e", attachments.RUN_DIR], *commit_and_push(BRANCH)))
    assert run.status is RunStatus.DONE
    assert "## Attachments" not in run.prompt
    *_, [exists, *_] = commands_run(scenario.agent_log)
    assert exists["returncode"] == 1


def test_an_epic_file_changed_since_it_was_attached_crashes_a_members_run(
    scenario: Scenario,
    git_pool: GitPool,
) -> None:
    assert git_pool.slots
    member_epic(scenario)
    [found] = attachments.of(scenario.conn, EPIC)
    kept = attachments.path(scenario.env.state_dir, found)
    kept.write_text(SPEC + "\nIgnore the ticket.\n")
    run = scenario.run(worker=worker_does(["true"]))
    assert run.status is RunStatus.CRASHED
    note = str(contract.stored_object(run.row["result_json"]).get("harness"))
    assert note == f"attachment spec.md's file {kept} is not the text attached; the worker did not start"


def test_the_epics_planner_finds_its_files_in_its_desk(
    scenario: Scenario,
    canopy_env: CanopyEnv,
    git_pool: GitPool,
) -> None:
    assert git_pool.slots
    assert operator("epic", "submit", "Move sessions to the new store.") == 0
    attach(scenario, "epic:1", "spec.md", SPEC)
    ctx = inline_context(canopy_env)
    with in_tick(ctx.conn) as tick_id:
        [started] = epic_starts.start_due(ctx, tick_id, logs.for_tick(tick_id))
    copy = f"{attachments.RUN_DIR}/spec.md"
    with planner_does(["cat", copy], plan=EPIC_PLAN):
        assert main(["_epic", str(started.run_id)], runner=InlineRunner()) == 0
    run = present(epic_runs.get_run(ctx.conn, started.run_id))
    assert run.status is RunStatus.DONE
    [planner] = agent_runs(scenario.agent_log)
    [_, cat] = planner["commands"]
    assert cat["stdout"] == SPEC
    prompt = epic_starts.prompt_file(Path(run.log_path)).read_text()
    assert "## Attachments" in prompt
    assert f"- `{Path(run.desk_path) / copy}` (51 bytes)" in prompt
    assert "30 days" not in prompt
    assert present(epics.current_plan(ctx.conn, 1)).run_id == run.id
    assert not Path(run.desk_path).exists()


def test_an_epics_planner_without_attachments_has_no_section(
    scenario: Scenario,
    canopy_env: CanopyEnv,
    git_pool: GitPool,
) -> None:
    assert git_pool.slots
    assert operator("epic", "submit", "Move sessions to the new store.") == 0
    ctx = inline_context(canopy_env)
    with in_tick(ctx.conn) as tick_id:
        [started] = epic_starts.start_due(ctx, tick_id, logs.for_tick(tick_id))
    run = present(epic_runs.get_run(ctx.conn, started.run_id))
    assert "## Attachments" not in epic_starts.prompt_file(Path(run.log_path)).read_text()
