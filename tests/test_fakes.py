"""The fakes are test infrastructure other tests rely on; pin their behavior here."""

import json
from pathlib import Path

import pytest

from canopy.procs import SubprocessRunner

run = SubprocessRunner().run


def treehouse(*args: str) -> tuple[int, str]:
    result = run(["treehouse", *args])
    return result.returncode, result.stdout


def test_treehouse_lease_roundtrip(treehouse_state: Path) -> None:
    assert treehouse("status", "--json") == (0, "[]\n")

    code, out = treehouse("get", "--lease", "--lease-holder", "canopy:PROJ-1", "--json")
    assert code == 0
    lease = json.loads(out)
    assert set(lease) == {"path", "lease_id", "lease_holder", "leased_at", "base_branch"}
    assert lease["lease_holder"] == "canopy:PROJ-1"
    assert lease["base_branch"] == "main"
    assert Path(lease["path"]).is_dir()

    code, out = treehouse("status", "--json")
    [slot] = json.loads(out)
    assert slot["status"] == "leased"
    assert slot["lease_id"] == lease["lease_id"]
    assert slot["leased_at"] == lease["leased_at"]

    args = ["--if-lease-id", lease["lease_id"], "--if-lease-holder", "canopy:PROJ-1", lease["path"]]
    assert treehouse("return", "--force", *args)[0] == 0
    [slot] = json.loads(treehouse("status", "--json")[1])
    assert slot["status"] == "available"
    assert slot["lease_id"] == ""
    assert slot["leased_at"] is None

    # The identity succeeds once: returning the same acquisition again fails.
    assert treehouse("return", "--force", *args)[0] == 1

    calls = json.loads(treehouse_state.read_text())["calls"]
    assert [c[0] for c in calls] == ["status", "get", "status", "return", "status", "return"]


def test_treehouse_reuses_available_slot_with_new_lease_id(treehouse_state: Path) -> None:
    first = json.loads(treehouse("get", "--lease", "--json")[1])
    assert treehouse("return", first["path"])[0] == 0
    second = json.loads(treehouse("get", "--lease", "--json", "--base", "agent/PROJ-1-x")[1])
    assert second["path"] == first["path"]
    assert second["lease_id"] != first["lease_id"]
    assert second["base_branch"] == "agent/PROJ-1-x"


def test_treehouse_return_rejects_wrong_lease_id(treehouse_state: Path) -> None:
    lease = json.loads(treehouse("get", "--lease", "--json")[1])
    assert treehouse("return", "--force", "--if-lease-id", "not-it", lease["path"])[0] == 1
    [slot] = json.loads(treehouse("status", "--json")[1])
    assert slot["status"] == "leased"


def test_treehouse_dirty_return_needs_force(treehouse_state: Path) -> None:
    treehouse_state.write_text(json.dumps({"slots": [{"name": "1", "path": "/pool/1/repo", "status": "dirty"}]}))
    assert treehouse("return", "1")[0] == 3  # noqa: PLR2004
    assert treehouse("return", "--force", "1")[0] == 0


def test_treehouse_pool_exhausted(treehouse_state: Path) -> None:
    treehouse_state.write_text(json.dumps({"max_trees": 1}))
    assert treehouse("get", "--lease")[0] == 0
    result = run(["treehouse", "get", "--lease"])
    assert result.returncode == 1
    assert "max_trees" in result.stderr


def test_agent_default_result_is_last_line(agent_log: Path) -> None:
    result = run(["agent", "--agent", "canopy-worker", "do the thing"])
    assert result.ok
    last = json.loads(result.stdout.splitlines()[-1])
    assert last["status"] == "done"
    assert json.loads(agent_log.read_text())["argv"] == ["--agent", "canopy-worker", "do the thing"]


@pytest.mark.parametrize("configured", ['{"status":"blocked","question":"which API?"}', "not json"])
def test_agent_prints_configured_result(agent_log: Path, monkeypatch: pytest.MonkeyPatch, configured: str) -> None:
    monkeypatch.setenv("FAKE_AGENT_RESULT", configured)
    assert run(["agent"]).stdout.splitlines()[-1] == configured
