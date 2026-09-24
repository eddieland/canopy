import json
from pathlib import Path

import pytest

from canopy import treehouse
from canopy.procs import SubprocessRunner

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
    assert outcome is treehouse.ReturnOutcome.RETURNED
    [slot] = treehouse.status(runner)
    assert (slot.status, slot.canopy_key, slot.leased_at) == ("available", None, None)
    # The lease is gone, so returning it again fails rather than touching whoever holds the slot next.
    again = treehouse.return_slot(runner, lease.path, lease_id=lease.lease_id, lease_holder=lease.lease_holder)
    assert again is treehouse.ReturnOutcome.FAILED

    calls = json.loads(treehouse_state.read_text())["calls"]
    assert calls[0] == ["get", "--lease", "--lease-holder", "canopy:PROJ-1", "--json"]
    assert calls[2][:2] == ["return", "--force"]


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


def test_missing_treehouse_is_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(treehouse.TreehouseError, match="command not found"):
        treehouse.status(runner)


@pytest.mark.parametrize("output", ["not json", "{}", '[{"name": "1"}]', '[{"name": 1, "path": "/p", "status": "x"}]'])
def test_unexpected_status_output_is_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: str) -> None:
    fake = tmp_path / "treehouse"
    fake.write_text(f"#!/bin/sh\nprintf '%s\\n' '{output}'\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(treehouse.TreehouseError, match="unexpected output"):
        treehouse.status(runner)


def test_status_tolerates_null_and_extra_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = tmp_path / "treehouse"
    row = '{"name": "1", "path": "/p", "status": "available", "lease_id": null, "leased_at": "", "future": 1}'
    fake.write_text(f"#!/bin/sh\necho '[{row}]'\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    [slot] = treehouse.status(runner)
    assert (slot.lease_id, slot.lease_holder, slot.leased_at, slot.canopy_key) == ("", "", None, None)
