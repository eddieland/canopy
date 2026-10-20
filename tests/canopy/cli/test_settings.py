"""The commands `canopy config commands` prints: each agent's, rendered from the operator's templates as a run would."""

import json
import os
import shlex
from unittest import mock

import pytest

from canopy.cli.main import main
from canopy.core import conversation
from tests.conftest import CanopyEnv

PLAN_CMD = (
    "env OPENCODE_CONFIG_DIR={definitions_dir} opencode run --agent canopy-planner --model 'some model' "
    "--title={title} {prompt}"
)


def test_each_agents_command_is_rendered_with_its_keys_and_their_files(
    canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]
) -> None:
    canopy_env.configure(
        canopy_env.private_file,
        {
            "runtime": {
                "plan_cmd": PLAN_CMD,
                "worker_cmd_prefix": "wrap --net off",
                "setup_cmd": "make setup",
            },
            "chores": {"build-health": {"prompt": "~/b.md", "every_minutes": 60, "cmd": "mytool --ask {prompt}"}},
        },
    )
    assert main(["config", "commands", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    found = {c["role"]: c for c in data["commands"]}
    assert list(found) == [
        "overseer",
        "worker",
        "private worker",
        "planner",
        "reviewer",
        "chore",
        "chore build-health",
        "setup",
    ]
    planner = found["planner"]
    assert planner["keys"] == [
        {"key": "runtime.worker_cmd_prefix", "set_in": "private"},
        {"key": "runtime.plan_cmd", "set_in": "private"},
    ]
    # The quoted model stays one word, and the title, the definitions, and the prompt land where the template put them.
    assert planner["argv"] == [
        "wrap",
        "--net",
        "off",
        "env",
        f"OPENCODE_CONFIG_DIR={data['definitions_dir']}",
        "opencode",
        "run",
        "--agent",
        "canopy-planner",
        "--model",
        "some model",
        "--title=PROJ-1 plan: Example ticket",
        "<prompt>",
    ]
    overseer = found["overseer"]
    assert overseer["keys"] == [{"key": "runtime.overseer_cmd", "set_in": "user"}]
    assert f"OPENCODE_CONFIG_DIR={data['definitions_dir']}" in overseer["argv"]
    assert found["reviewer"]["keys"] == [{"key": "runtime.review_cmd", "set_in": None}]
    # Only a worker run's commands are wrapped.
    assert found["reviewer"]["argv"][0] == "env"
    assert found["chore build-health"]["argv"] == ["mytool", "--ask", "<prompt>"]
    assert found["setup"]["argv"] == ["make", "setup"]


def test_the_text_quotes_each_command_for_a_shell(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    canopy_env.configure(canopy_env.private_file, {"runtime": {"plan_cmd": PLAN_CMD}})
    assert main(["config", "commands"]) == 0
    out = capsys.readouterr().out
    [definitions_dir] = {w.partition("=")[2] for w in shlex.split(out) if w.startswith("OPENCODE_CONFIG_DIR=")}
    assert "\nplanner: runtime.plan_cmd (private file)\n" in out
    assert "\noverseer: runtime.overseer_cmd (user file)\n" in out
    assert "\nreviewer: runtime.review_cmd (default)\n" in out
    line = shlex.join(
        [
            "env",
            f"OPENCODE_CONFIG_DIR={definitions_dir}",
            *shlex.split("opencode run --agent canopy-planner --model"),
            "some model",
            "--title=PROJ-1 plan: Example ticket",
            "<prompt>",
        ]
    )
    assert f"\n  {line}\n" in out
    assert "setup:" not in out


def test_it_is_refused_inside_a_tick(canopy_env: CanopyEnv, capsys: pytest.CaptureFixture[str]) -> None:
    canopy_env.configure(canopy_env.private_file, {"runtime": {"setup_cmd": "make setup TOKEN=s3cret"}})
    with mock.patch.dict(os.environ, {conversation.TICK_ID_ENV: "1"}):
        assert main(["config", "commands"]) == 1
    captured = capsys.readouterr()
    assert "config commands refused (inside_run)" in captured.err
    assert "s3cret" not in captured.out + captured.err
