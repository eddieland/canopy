"""The keys `canopy config show` prints: each with its value, its default, its bounds, and the file that set it."""

import json
import re

import pytest

from canopy.cli.main import main
from canopy.core import config
from tests.conftest import CanopyEnv


def test_each_key_says_its_value_its_default_and_the_file_that_set_it(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    canopy_env.configure(canopy_env.private_file, {"capacity": {"max_workers": 4}})
    canopy_env.configure(canopy_env.root / config.WORKSPACE_FILE_NAME, {"policy": {"max_resume_attempts": 1}})
    assert main(["config", "show", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["files"] == {
        "workspace": str(canopy_env.root / config.WORKSPACE_FILE_NAME),
        "user": str(canopy_env.user_file),
        "private": str(canopy_env.private_file),
    }
    found = {s["key"]: s for s in data["settings"]}
    assert found["capacity.max_workers"] == {
        "key": "capacity.max_workers",
        "value": 4,
        "default": 2,
        "set_in": "private",
        "required": False,
        "choices": [],
        "minimum": 0,
        "maximum": None,
    }
    assert (found["policy.max_resume_attempts"]["value"], found["policy.max_resume_attempts"]["set_in"]) == (
        1,
        "workspace",
    )
    assert (found["loop.idle_max_minutes"]["set_in"], found["loop.idle_max_minutes"]["value"]) == (
        None,
        config.Loop().idle_max_minutes,
    )
    assert found["policy.plan"]["choices"] == ["off", "approve"]
    assert found["memory.ticket_notes"]["choices"] == ["off", "record", "use"]
    # Optional, and bounded through the type it is optional of.
    assert (found["capacity.slots_per_repo"]["value"], found["capacity.slots_per_repo"]["minimum"]) == (None, 0)


def test_a_workspace_files_policy_value_that_does_not_tighten_is_not_what_set_it(
    canopy_env: CanopyEnv,
    capsys: pytest.CaptureFixture[str],
) -> None:
    loose = config.Policy().max_resume_attempts + 5
    canopy_env.configure(canopy_env.root / config.WORKSPACE_FILE_NAME, {"policy": {"max_resume_attempts": loose}})
    assert main(["config", "show", "--json"]) == 0
    [found] = [s for s in json.loads(capsys.readouterr().out)["settings"] if s["key"] == "policy.max_resume_attempts"]
    assert (found["value"], found["set_in"]) == (config.Policy().max_resume_attempts, None)


def test_text_commands_and_paths_are_left_out(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    canopy_env.configure(
        canopy_env.private_file,
        {
            "runtime": {"setup_cmd": "make setup TOKEN=s3cret"},
            "chores": {
                "build-health": {
                    "prompt": "~/chores/build-health.md",
                    "every_minutes": 60,
                    "days": ["mon", "tue"],
                    "when": "Skip it on a quiet day.",
                },
            },
        },
    )
    assert main(["config", "show", "--json"]) == 0
    out = capsys.readouterr().out
    keys = {s["key"]: s for s in json.loads(out)["settings"]}
    assert "s3cret" not in out
    for left_out in ("runtime.setup_cmd", "runtime.worker_cmd", "tracker.query", "paths.prompt_overrides"):
        assert left_out not in keys
    # A chore's schedule is shown, from the file that holds its table; its prompt and its `when` are text.
    assert {k for k in keys if k.startswith("chores.")} == {
        "chores.build-health.every_minutes",
        "chores.build-health.days",
        "chores.build-health.max_findings",
        "chores.build-health.timeout_minutes",
    }
    days = keys["chores.build-health.days"]
    assert (days["value"], days["set_in"], days["choices"][:2]) == (["mon", "tue"], "private", ["mon", "tue"])
    every = keys["chores.build-health.every_minutes"]
    assert (every["default"], every["required"]) == (None, True)
    # A key its table leaves to the default is the default's, not the file's.
    assert keys["chores.build-health.max_findings"]["set_in"] is None


def test_the_text_says_which_file_set_each_key(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    canopy_env.configure(canopy_env.private_file, {"capacity": {"max_workers": 4}})
    assert main(["config", "show"]) == 0
    out = capsys.readouterr().out
    assert f"  private file: {canopy_env.private_file}\n" in out
    assert re.search(r"\n  capacity\.max_workers +4  \(private file; default 2; at least 0\)\n", out)
    assert re.search(r"\n  policy\.plan +\"off\"  \(default; one of off, approve\)\n", out)
