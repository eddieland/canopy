"""The fakes are test infrastructure other tests rely on; pin their behavior here."""

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from canopy.infra.procs import SubprocessRunner

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
    assert treehouse("return", "1")[0] == 3
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
def test_agent_prints_configured_result(agent_log: Path, configured: str) -> None:
    with mock.patch.dict(os.environ, {"FAKE_AGENT_RESULT": configured}):
        assert run(["agent"]).stdout.splitlines()[-1] == configured


def test_agent_reads_the_settings_of_the_ticket_its_title_names_first(agent_log: Path) -> None:
    tickets = {"PROJ-2": {"RESULT": "for PROJ-2", "EXIT": "3"}}
    env = {"FAKE_WORKER_RESULT": "for the role", "FAKE_WORKER_FOR": json.dumps(tickets)}
    with mock.patch.dict(os.environ, env):
        theirs = run(["agent", "--agent", "canopy-worker", "--title=PROJ-2 implement: Log in", "PROJ-1 in the prompt"])
        assert (theirs.returncode, theirs.stdout.splitlines()[-1]) == (3, "for PROJ-2")
        for untitled in (["--title=PROJ-1 resume", "PROJ-2"], ["PROJ-2"]):
            other = run(["agent", "--agent", "canopy-worker", *untitled])
            assert (other.returncode, other.stdout.splitlines()[-1]) == (0, "for the role")


PR = "https://github.com/acme/api/pull/7"
COMMENT = {
    "item": "comment",
    "id": 501,
    "author": "alice",
    "bot": False,
    "time": "2026-10-18T10:00:00Z",
    "body": "Rename this.",
    "thread": {"id": "PRRT_1", "path": "a.py", "line": 3, "side": "right", "outdated": False, "resolved": False},
}


def github(program: str, request: object) -> tuple[int, list[dict[str, object]]]:
    result = run([f"canopy-{program}-github"], stdin=json.dumps(request))
    return result.returncode, [json.loads(line) for line in result.stdout.splitlines()]


def test_the_github_fake_reads_what_its_state_holds_and_posts_into_it(github_state: Path) -> None:
    assert github("connect", {"prs": [PR]}) == (1, [{"kind": "end", "prs": []}])
    github_state.write_text(json.dumps({"prs": {PR: {"reviews": [COMMENT]}}}))
    code, lines = github("connect", {"prs": [PR]})
    assert code == 0
    assert [line["kind"] for line in lines] == ["pr", "review", "end"]
    assert lines[1] == {"kind": "review", "pr": PR, **COMMENT}

    code, lines = github("post", {"pr": PR, "body": "Done.", "replies": [{"comment": 501, "text": "Renamed."}]})
    assert code == 0
    assert [line["kind"] for line in lines] == ["as", "pending", "comment", "review", "end"]
    _, read = github("connect", {"prs": [PR]})
    reply = next(line for line in read if line.get("body") == "Renamed.")
    assert (reply["author"], reply["thread"]) == ("me", COMMENT["thread"])
    [log, *_] = [json.loads(line) for line in (github_state.parent / "github.jsonl").read_text().splitlines()]
    assert log == {"program": "connect", "request": {"prs": [PR]}}


@pytest.mark.parametrize(
    ("post", "kinds", "code"),
    [("refused", ["as", "end"], 1), ("pending_left", ["as", "pending", "end"], 1), ("unknown", ["as", "pending"], 1)],
)
def test_the_github_fake_ends_a_post_as_told(github_state: Path, post: str, kinds: list[str], code: int) -> None:
    github_state.write_text(json.dumps({"prs": {PR: {"reviews": [COMMENT]}}, "post": post}))
    found, lines = github("post", {"pr": PR, "replies": [{"comment": 501, "text": "Renamed."}]})
    assert (found, [line["kind"] for line in lines]) == (code, kinds)
