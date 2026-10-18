import json
import os
from pathlib import Path
from unittest import mock

import pytest

from canopy.core import pools, treehouse
from canopy.infra.procs import SubprocessRunner
from tests.conftest import executable

runner = SubprocessRunner()


def test_status_of_empty_pool(treehouse_state: Path) -> None:
    assert treehouse.status(runner) == []


def test_lease_status_and_return(treehouse_state: Path) -> None:
    lease = treehouse.lease(runner, "PROJ-1")
    assert lease.lease_holder == "canopy:PROJ-1"
    assert lease.base_branch == "main"
    [slot] = treehouse.status(runner)
    assert slot.canopy_key == "PROJ-1"
    assert slot.lease_id == lease.lease_id
    assert slot.leased_at == lease.leased_at

    outcome = treehouse.return_slot(runner, lease.path, lease_id=lease.lease_id, lease_holder=lease.lease_holder)
    assert outcome is pools.ReturnOutcome.RETURNED
    [slot] = treehouse.status(runner)
    assert (slot.status, slot.canopy_key, slot.leased_at) == ("available", None, None)
    # The lease is gone, so returning it again fails rather than touching whoever holds the slot next.
    again = treehouse.return_slot(runner, lease.path, lease_id=lease.lease_id, lease_holder=lease.lease_holder)
    assert again is pools.ReturnOutcome.FAILED

    calls = json.loads(treehouse_state.read_text())["calls"]
    assert calls[0] == ["get", "--lease", "--lease-holder", "canopy:PROJ-1", "--json"]
    assert calls[2][:2] == ["return", "--force"]


def test_release_returns_only_a_quarantined_slot(treehouse_state: Path) -> None:
    lease = treehouse.lease(runner, "PROJ-1")
    assert treehouse.release(runner, lease.path) is pools.ReturnOutcome.FAILED
    assert treehouse.status(runner)[0].canopy_key == "PROJ-1"
    treehouse.return_slot(runner, lease.path, lease_id=lease.lease_id, lease_holder=lease.lease_holder)
    assert runner.run(["treehouse", "get", "--lease", "--lease-holder", pools.QUARANTINED]).ok
    assert treehouse.release(runner, lease.path) is pools.ReturnOutcome.RETURNED
    [slot] = treehouse.status(runner)
    assert (slot.status, slot.lease_holder) == ("available", "")
    calls = json.loads(treehouse_state.read_text())["calls"]
    assert calls[-2] == ["return", "--force", "--if-lease-holder", pools.QUARANTINED, str(lease.path)]


def test_lease_with_base(treehouse_state: Path) -> None:
    assert treehouse.lease(runner, "PROJ-2", base="agent/PROJ-1-x").base_branch == "agent/PROJ-1-x"


def test_other_holders_are_not_canopy(treehouse_state: Path) -> None:
    run = runner.run(["treehouse", "get", "--lease", "--lease-holder", "someone-else"])
    assert run.ok
    [slot] = treehouse.status(runner)
    assert slot.canopy_key is None


def test_pool_exhausted_is_an_error(treehouse_state: Path) -> None:
    treehouse_state.write_text(json.dumps({"max_trees": 0}))
    with pytest.raises(treehouse.TreehouseError, match="max_trees"):
        treehouse.lease(runner, "PROJ-1")


def test_unparseable_lease_is_returned(treehouse_state: Path) -> None:
    treehouse_state.write_text(json.dumps({"get_omit": ["base_branch"]}))
    with pytest.raises(treehouse.TreehouseError, match=r"base_branch(.|\n)*; returned .*/pool/1/repo"):
        treehouse.lease(runner, "PROJ-1")
    [slot] = treehouse.status(runner)
    assert (slot.status, slot.canopy_key) == ("available", None)
    calls = json.loads(treehouse_state.read_text())["calls"]
    assert [c[0] for c in calls] == ["get", "return", "status"]


def test_unidentifiable_lease_is_left_for_reconcile(treehouse_state: Path) -> None:
    treehouse_state.write_text(json.dumps({"get_omit": ["lease_id"]}))
    with pytest.raises(treehouse.TreehouseError, match="the next tick's reconcile returns it"):
        treehouse.lease(runner, "PROJ-1")
    [slot] = treehouse.status(runner)
    assert slot.canopy_key == "PROJ-1"


def test_missing_treehouse_is_an_error(tmp_path: Path) -> None:
    with (
        mock.patch.dict(os.environ, {"PATH": str(tmp_path)}),
        pytest.raises(treehouse.TreehouseError, match="command not found"),
    ):
        treehouse.status(runner)


@pytest.mark.parametrize("output", ["not json", "{}", '[{"name": "1"}]', '[{"name": 1, "path": "/p", "status": "x"}]'])
def test_unexpected_status_output_is_an_error(tmp_path: Path, output: str) -> None:
    fake = tmp_path / "treehouse"
    executable(fake, f"#!/bin/sh\nprintf '%s\\n' '{output}'\n")
    with (
        mock.patch.dict(os.environ, {"PATH": str(tmp_path)}),
        pytest.raises(treehouse.TreehouseError, match="unexpected output"),
    ):
        treehouse.status(runner)


def test_status_tolerates_null_and_extra_fields(tmp_path: Path) -> None:
    fake = tmp_path / "treehouse"
    row = '{"name": "1", "path": "/p", "status": "available", "lease_id": null, "leased_at": "", "future": 1}'
    executable(fake, f"#!/bin/sh\necho '[{row}]'\n")
    with mock.patch.dict(os.environ, {"PATH": str(tmp_path)}):
        [slot] = treehouse.status(runner)
        assert (slot.lease_id, slot.lease_holder, slot.leased_at, slot.canopy_key) == ("", "", None, None)
