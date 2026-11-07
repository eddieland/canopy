"""The operator stopping an epic through the web UI (DESIGN §43, TRUST_MODEL T1).

A stop writes through the function `canopy stop epic:N` calls, refused as the CLI's is, and ends the plan run at work
only when the operator asks, as `--now` does. It ends only the epic's planning: its members and its waiting plan stay.
"""

import json
from pathlib import Path

from canopy.core import epics
from canopy.core.vocab import PlanStatus, RunStatus
from canopy.infra import logs
from canopy.runs import epic_runs, epic_starts
from canopy.serve.backend import Backend
from canopy.serve.mock import epics as mock_epics
from tests.canopy.helpers import in_run, in_tick, inline_context, operator, pool_statuses, present
from tests.canopy.web_helpers import refused, signed_in_client, signed_in_to
from tests.conftest import CanopyEnv, GitPool

APPROVED, PROPOSED, PLANNING = mock_epics.APPROVED, mock_epics.PROPOSED, mock_epics.PLANNING
#: A reply's form, with the submission id it drew.
REPLY = {"body": "Keep the web page's list as it is.", "submission": "form-0001"}


def test_a_stop_from_the_web_ends_the_epics_planning_and_leaves_its_plan_and_members(backend: Backend) -> None:
    """Stopped, it stands `stopped` with when, takes no reply, and its waiting plan may still be approved."""
    c, headers = signed_in_to(backend)
    route = f"/api/epics/{PROPOSED}/stop"
    # A write needs the session's token, as every write does.
    assert c.post(route, json={"now": False}).status_code == 403

    stopped = c.post(route, json={"now": False}, headers=headers).json()
    assert stopped == {"already": False, "running_run": None, "ended": False, "kept": False}
    listed = {e["id"]: e for e in c.get("/api/epics").json()}
    assert (listed[PROPOSED]["standing"], listed[PROPOSED]["stopped_at"] is not None) == ("stopped", True)
    assert listed[APPROVED]["stopped_at"] is None
    with backend.open() as ctx:
        assert present(epics.get(ctx.conn, PROPOSED)).stopped_at is not None
    said = refused(c.post(f"/api/epics/{PROPOSED}/replies", json=REPLY, headers=headers))
    assert said.startswith("stopped: epic:2 is stopped")

    again = c.post(route, json={"now": True}, headers=headers).json()
    assert again == {"already": True, "running_run": None, "ended": False, "kept": False}
    sha256 = c.get(f"/api/epics/{PROPOSED}/plans").json()["plans"][-1]["sha256"]
    approval = c.post(f"/api/epics/{PROPOSED}/plan/approval", json={"read_sha256": sha256}, headers=headers)
    assert approval.status_code == 200
    with backend.open() as ctx:
        assert present(epics.current_plan(ctx.conn, PROPOSED)).status is PlanStatus.APPROVED


def test_stop_lets_the_plan_run_finish_and_stop_now_ends_it(backend: Backend) -> None:
    """The mock's plan run at work keeps working through a stop, and `now` closes it, as the mock ends a run."""
    c, headers = signed_in_to(backend)
    route = f"/api/epics/{PLANNING}/stop"
    with backend.open() as ctx:
        [run] = [r for r in epic_runs.runs_of(ctx.conn, PLANNING) if r.status is RunStatus.RUNNING]

    graceful = c.post(route, json={"now": False}, headers=headers).json()
    assert graceful == {"already": False, "running_run": run.id, "ended": False, "kept": False}
    found = c.get(f"/api/epics/{PLANNING}").json()["epic"]
    assert (found["standing"], found["stopped_at"] is not None) == ("planning", True)

    now = c.post(route, json={"now": True}, headers=headers).json()
    assert now == {"already": True, "running_run": run.id, "ended": True, "kept": False}
    assert c.get(f"/api/epics/{PLANNING}").json()["epic"]["standing"] == "stopped"
    with backend.open() as ctx:
        assert present(epic_runs.get_run(ctx.conn, run.id)).status is RunStatus.STOPPED


def test_a_stop_is_refused_inside_a_run_and_for_no_epic(backend: Backend) -> None:
    c, headers = signed_in_to(backend)
    assert refused(c.post("/api/epics/99/stop", json={"now": False}, headers=headers)) == (
        "unknown_epic: canopy has no epic:99"
    )
    with in_run(7):
        assert refused(c.post(f"/api/epics/{PROPOSED}/stop", json={"now": True}, headers=headers)).startswith(
            "inside_run",
        )
    with backend.open() as ctx:
        assert present(epics.get(ctx.conn, PROPOSED)).stopped_at is None


def test_stop_now_from_the_web_ends_the_plan_run_and_returns_its_slots_as_canopy_stop_now_does(
    canopy_env: CanopyEnv,
    git_pool: GitPool,
    treehouse_state: Path,
) -> None:
    """Through the loop's server, `now` kills the plan run, closes it `stopped`, and returns its slot."""
    assert git_pool.slots
    ctx = inline_context(canopy_env)
    c, headers = signed_in_client(ctx)
    assert operator("epic", "submit", "Move sessions to the new store.") == 0
    with in_tick(ctx.conn) as tick_id:
        [started] = epic_starts.start_due(ctx, tick_id, logs.for_tick(tick_id))

    now = c.post("/api/epics/1/stop", json={"now": True}, headers=headers).json()
    assert now == {"already": False, "running_run": started.run_id, "ended": True, "kept": False}
    run = present(epic_runs.get_run(ctx.conn, started.run_id))
    assert run.status is RunStatus.STOPPED
    assert json.loads(present(run.result_json))["harness"] == epic_runs.STOP_NOTE
    assert set(pool_statuses(treehouse_state)) == {"available"}
