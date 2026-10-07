"""`canopy check` (DESIGN §13, D070): agents try what their tools allow on made-up targets, and the harness judges."""

import json
import re
from pathlib import Path

import pytest

from canopy.cli.main import main
from canopy.core import config
from canopy.infra import resources
from canopy.setup import check
from tests.conftest import CanopyEnv


def result_line(outcomes: dict[str, str], *, tools: tuple[str, ...] = ("jira_getJiraIssue",)) -> str:
    results = [
        {"id": step, "outcome": outcome, "tool": "jira_tool", "detail": "fake"} for step, outcome in outcomes.items()
    ]
    return json.dumps({"tools": list(tools), "results": results})


def passing(agent: check.Agent, *, ticket: str | None = None) -> dict[str, str]:
    """Outcomes that satisfy every expectation `agent` has."""
    return {
        step: "reached" if expect == "allowed" else "refused"
        for step, expect in check.steps_for(agent, ticket=ticket).items()
    }


WORKER = check.AGENTS[check.AGENT_NAMES.index("worker")]


@pytest.mark.parametrize(
    ("expect", "outcome", "verdict"),
    [
        ("allowed", "reached", "ok"),
        ("allowed", "refused", "fail"),
        ("allowed", "no_tool", "fail"),
        ("allowed", "failed", "fail"),
        ("allowed", None, "fail"),
        ("denied", "no_tool", "ok"),
        ("denied", "refused", "ok"),
        ("denied", "reached", "fail"),
        ("denied", None, "fail"),
        ("prompt", "refused", "ok"),
        ("prompt", "reached", "warn"),
        ("any", "reached", "info"),
        ("any", None, "info"),
    ],
)
def test_judge(expect: check.Expect, outcome: check.Outcome | None, verdict: check.Verdict) -> None:
    assert check.judge(expect, outcome) == verdict


def test_every_agent_is_one_of_canopys_and_opens_its_prompt_the_way_its_definition_requires() -> None:
    for agent in check.AGENTS:
        body = (resources.agents_dir() / f"{agent.definition}.md").read_text()
        wanted = re.search(r'started without a "([^"]+)" prompt', body)
        if wanted is not None:
            assert agent.header.startswith(wanted.group(1)), agent.name
        else:
            # The chore's definition wants a prompt ending in a "## Run" section instead.
            assert '"## Run" section' in body, agent.name
    text = (resources.prompts_dir() / check.PROMPT).read_text()
    assert text.rstrip().rsplit("\n## ", 1)[1].startswith("Run\n")


def test_no_agent_may_merge_review_or_transition() -> None:
    for agent in check.AGENTS:
        for step in ("merge_pr", "review_pr", "transition_ticket", "write_file", "create_branch", "delete"):
            assert agent.expect[step] == "denied", (agent.name, step)
        assert set(agent.expect) <= set(check.STEPS), agent.name


def test_prompt_targets_names_that_cannot_exist_for_the_tracker(canopy_env: CanopyEnv) -> None:
    cfg = config.load(canopy_env.repo)
    text = check.render_prompt(cfg, WORKER, ticket=None)
    assert text.startswith("# canopy worker: permission check\n")
    assert "`9CANOPYCHECK-1`" in text
    assert "`canopy--check/missing`" in text
    assert check.ROUND_TRIP not in text
    github = cfg.model_copy(update={"tracker": cfg.tracker.model_copy(update={"provider": "github"})})
    assert "issue 1 in `canopy--check/missing`" in check.render_prompt(github, WORKER, ticket=None)


def test_a_real_ticket_adds_the_label_round_trip_for_the_worker_only(canopy_env: CanopyEnv) -> None:
    cfg = config.load(canopy_env.repo)
    text = check.render_prompt(cfg, WORKER, ticket="PROJ-7")
    assert "On the real ticket `PROJ-7`: add the label `needs-human`" in text
    for agent in check.AGENTS:
        if agent is not WORKER:
            assert check.ROUND_TRIP not in check.steps_for(agent, ticket="PROJ-7"), agent.name


def test_check_passes_when_every_step_comes_out_as_expected(
    canopy_env: CanopyEnv, agent_log: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("FAKE_WORKER_RESULT", result_line(passing(WORKER)))
    assert main(["check", "--agent", "worker"]) == 0
    out = capsys.readouterr().out
    assert "canopy-worker:" in out
    assert "tools: jira_getJiraIssue" in out
    assert "FAIL" not in out
    assert "  INFO  label_pr" in out
    run = json.loads(agent_log.read_text().splitlines()[-1])
    assert run["argv"][-1].startswith("# canopy worker: permission check")
    assert Path(run["cwd"]) == canopy_env.state_dir / "checks" / "worker"
    log = (canopy_env.state_dir / "checks" / "worker.log").read_text()
    assert "--- prompt ---" in log
    assert "--- exit 0 ---" in log


def test_check_fails_when_a_forbidden_step_is_reached(
    canopy_env: CanopyEnv, agent_log: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    outcomes = passing(WORKER) | {"create_ticket": "reached", "close_pr": "reached"}
    monkeypatch.setenv("FAKE_WORKER_RESULT", result_line(outcomes))
    assert main(["check", "--agent", "worker"]) == 1
    out = capsys.readouterr().out
    assert "  FAIL  create_ticket" in out
    assert "reached via jira_tool (must be refused or have no tool): fake" in out
    assert "  WARN  close_pr" in out


def test_a_step_the_agent_does_not_report_fails(
    canopy_env: CanopyEnv, agent_log: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    outcomes = passing(WORKER)
    del outcomes["merge_pr"]
    monkeypatch.setenv("FAKE_WORKER_RESULT", result_line(outcomes))
    assert main(["check", "--agent", "worker"]) == 1
    assert "  FAIL  merge_pr" in capsys.readouterr().out


def test_a_run_without_a_valid_result_fails(
    canopy_env: CanopyEnv, agent_log: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("FAKE_WORKER_RESULT", "not json")
    assert main(["check", "--agent", "worker"]) == 1
    assert "FAIL  its last line was not a valid result" in capsys.readouterr().out


def test_every_agent_runs_through_its_own_template(
    canopy_env: CanopyEnv, agent_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for agent in check.AGENTS:
        monkeypatch.setenv(
            f"FAKE_{agent.definition.removeprefix('canopy-').upper()}_RESULT", result_line(passing(agent))
        )
    user = canopy_env.user_file.read_text()
    templates = "".join(
        f"{key} = 'env OPENCODE_CONFIG_DIR={{definitions_dir}} agent run --agent {name} {{prompt}}'\n"
        for key, name in (("review_cmd", "canopy-reviewer"), ("chore_cmd", "canopy-chore"))
    )
    canopy_env.user_file.write_text(user.replace("[runtime]\n", f"[runtime]\n{templates}", 1))
    assert main(["check"]) == 0
    runs = [json.loads(line) for line in agent_log.read_text().splitlines()]
    assert [r["argv"][r["argv"].index("--agent") + 1] for r in runs] == [a.definition for a in check.AGENTS]


def test_the_ticket_round_trip_needs_the_worker(canopy_env: CanopyEnv, agent_log: Path) -> None:
    assert main(["check", "--agent", "reviewer", "--ticket", "PROJ-7"]) == 2
    assert not agent_log.exists()
