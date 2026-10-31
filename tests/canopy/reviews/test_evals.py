"""`canopy review eval` (DESIGN §21, Scoring the reviewer): the reviewer scored on the operator's cases.

Each case is reviewed as a review is, in a slot at its commit, its base named to the reviewer, and scored: a bug case on
whether a finding is within a few lines of a line the operator confirmed, a clean case on its findings. Nothing reaches
the journal; the score goes to the state directory, with what it ran with.
"""

import json
import os
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from canopy.core import records, sql
from canopy.core.context import Context
from canopy.infra import resources
from canopy.reviews import evals
from tests.canopy.helpers import agent_runs, listed, personas_dir, pool_statuses, told
from tests.canopy.review_helpers import CLEAN, PR, REPORT, THEIRS, feature_commit, head, reviewer_reports
from tests.canopy.scenario_helpers import Scenario
from tests.conftest import CanopyEnv, GitPool

MODEL = "acme/fake-model-1"


def case(name: str, sha: str, base: str, *lines: str, pr: str = PR, repo: str = "repo") -> dict[str, object]:
    """An eval case of `pr` at `sha` from `base`: a bug case on `lines`, a clean one without any."""
    found: dict[str, object] = {"name": name, "pr": pr, "repo": repo, "sha": sha, "base": base}
    return found | ({"kind": "bug", "lines": list(lines)} if lines else {"kind": "clean"})


@pytest.fixture
def commits(reviewing: CanopyEnv, git_pool: GitPool, tmp_path: Path) -> tuple[str, str]:
    """The commit `feature_commit` pushes, which adds `retry.py`, and the commit on `main` it starts from."""
    del reviewing
    base = head(git_pool)
    return feature_commit(git_pool, tmp_path), base


def cases(scenario: Scenario, *found: Mapping[str, object]) -> None:
    """Make `found` the eval's cases, in the workspace's private config."""
    scenario.configures("private", review={"eval_cases": list(found)})


def saved(env: CanopyEnv) -> dict[str, Any]:
    """The latest eval's result, as it saved it."""
    [path] = sorted((env.state_dir / evals.EVALS_DIR).glob("*.json"))[-1:]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    result: dict[str, Any] = json.loads(path.read_text())
    return result


def journal_rows(scenario: Scenario, tables: Sequence[str]) -> dict[str, int]:
    """How many rows each of `tables` holds."""
    return {t: scenario.conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}  # noqa: S608


def test_an_eval_scores_the_reviewer_and_records_nothing_in_the_journal(
    scenario: Scenario,
    commits: tuple[str, str],
    treehouse_state: Path,
    agent_log: Path,
) -> None:
    sha, base = commits
    cases(scenario, case("retry", sha, base, "retry.py:2"), case("sound", sha, base, pr=THEIRS))
    # A notice is about the loop's runs now, not about a commit an eval reads: no eval's prompt carries one.
    scenario.operator("notice", "CI is down.")
    with reviewer_reports(REPORT, ["git", "-C", "checkout", "merge-base", f"origin/{evals.BASE_BRANCH}", "HEAD"]):
        printed = scenario.operator("review", "eval")

    assert "| retry | bug | done | found at `retry.py:1` (blocking) |" in printed.out
    assert "| sound | clean | done | 2 false alarms: 1 blocking, 1 minor |" in printed.out
    assert "Recall: 1 of 1 bug cases. False alarms: 1 of 1 clean cases, 1 blocking, 0 major, 1 minor." in printed.out
    assert printed.out.startswith("## ")
    assert "reviewing case 1 of 2, retry" in printed.err

    # Each case is reviewed at its commit, in a directory of the eval's outside the checkout, its base named.
    first, second = agent_runs(agent_log)
    where = scenario.env.state_dir / evals.EVALS_DIR
    for run in (first, second):
        assert Path(run["cwd"]).parent.parent == where
        assert run["argv"][:3] == ["run", "--agent", "canopy-reviewer"]
        assert "CANOPY_TICK_ID" not in run["env"]
        assert run["env"]["CANOPY_RUN_ID"].startswith("review-eval-")
        [merge_base] = run["commands"]
        assert merge_base["stdout"].strip() == base
        prompt = told(run)
        assert f"- Base: `{evals.BASE_BRANCH}`" in prompt
        assert "CI is down." not in prompt
        assert not Path(run["cwd"]).exists()
    assert pool_statuses(treehouse_state) == ["available", "available"]

    # Nothing of it is the loop's: no review run, draft, attention item, notification, or tick.
    tables = ("review_runs", "review_drafts", "review_holds", "decisions", "ticks", "notify_events")
    assert journal_rows(scenario, tables) == dict.fromkeys(tables, 0)
    assert scenario.attention() == []

    result = saved(scenario.env)
    assert result["recall"] == {"found": 1, "of": 1}
    assert result["false_alarms"] == {"cases": 1, "of": 1, "blocking": 1, "major": 0, "minor": 1}
    assert result["persona"]["name"] == "canopy"
    assert len(result["prompt"]["digest"]) == 64
    assert result["prompt"]["yours"] is False
    assert result["model"] is None
    assert result["tolerance"] == evals.TOLERANCE
    assert [(c["name"], c["status"], c["found"]) for c in result["cases"]] == [
        ("retry", "done", {"location": "retry.py:1", "severity": "blocking"}),
        ("sound", "done", None),
    ]
    # Its prompts and logs stay beside the result, the operator's alone.
    [kept] = [p for p in where.iterdir() if p.is_dir()]
    assert sorted(p.name for p in kept.iterdir()) == ["retry.log", "retry.prompt", "sound.log", "sound.prompt"]
    assert "--- reviewer exit 0 ---" in (kept / "retry.log").read_text()


@pytest.mark.parametrize(
    ("line", "found"),
    [
        ("retry.py:4", True),  # within the tolerance of the finding's line 1
        ("retry.py:5", False),
        ("./retry.py:3-9", True),
        ("other.py:1", False),
    ],
)
def test_a_bug_is_found_by_a_finding_within_a_few_lines_of_a_confirmed_one(
    scenario: Scenario,
    commits: tuple[str, str],
    line: str,
    *,
    found: bool,
) -> None:
    sha, base = commits
    cases(scenario, case("retry", sha, base, line))
    with reviewer_reports(REPORT):
        scenario.operator("review", "eval")
    assert saved(scenario.env)["recall"] == {"found": int(found), "of": 1}


def test_a_review_that_ends_any_way_but_done_is_not_scored(scenario: Scenario, commits: tuple[str, str]) -> None:
    sha, base = commits
    cases(scenario, case("retry", sha, base, "retry.py:1"), case("sound", sha, base, pr=THEIRS))
    with reviewer_reports("no result line"):
        printed = scenario.operator("review", "eval")
    assert "| retry | bug | unknown | not scored: the reviewer's last line was not a valid result |" in printed.out
    assert "Recall: 0 of 0 bug cases. False alarms: 0 of 0 clean cases" in printed.out


def test_a_clean_review_misses_the_bug(scenario: Scenario, commits: tuple[str, str]) -> None:
    sha, base = commits
    cases(scenario, case("retry", sha, base, "retry.py:1"), case("sound", sha, base, pr=THEIRS))
    with reviewer_reports(CLEAN):
        printed = scenario.operator("review", "eval", "--json")
    result = json.loads(printed.out)
    assert result["recall"] == {"found": 0, "of": 1}
    assert result["false_alarms"] == {"cases": 0, "of": 1, "blocking": 0, "major": 0, "minor": 0}


def test_a_case_waits_for_review_capacity_as_any_review_does(
    scenario: Scenario,
    commits: tuple[str, str],
    agent_log: Path,
) -> None:
    sha, base = commits
    cases(scenario, case("retry", sha, base, "retry.py:1"))
    scenario.configures(capacity={"max_reviews": 0})
    printed = scenario.operator("review", "eval")
    assert "| retry | bug | refused | not scored: review_capacity: 0 of 0 review runs are running |" in printed.out
    assert agent_runs(agent_log) == []


def test_an_eval_returns_a_slot_an_eval_that_died_left_leased(
    scenario: Scenario,
    commits: tuple[str, str],
    treehouse_state: Path,
    ctx: Context,
) -> None:
    sha, base = commits
    ctx.pool("repo").lease_as(evals.HOLDER)
    assert sorted(pool_statuses(treehouse_state)) == ["available", "leased"]
    cases(scenario, case("retry", sha, base, "retry.py:1"))
    with reviewer_reports(CLEAN):
        scenario.operator("review", "eval")
    assert pool_statuses(treehouse_state) == ["available", "available"]


def test_an_eval_runs_in_the_persona_and_on_the_model_it_is_given(
    scenario: Scenario,
    commits: tuple[str, str],
    opencode_state: Path,
    agent_log: Path,
) -> None:
    sha, base = commits
    cases(scenario, case("retry", sha, base, "retry.py:1"))
    (personas_dir(scenario.env) / "terse.md").write_text("Be terse.\n")
    listed(opencode_state, MODEL)
    with reviewer_reports(CLEAN):
        result = json.loads(scenario.operator("review", "eval", "--persona", "terse", "--model", MODEL, "--json").out)
    assert result["persona"]["name"] == "terse"
    assert result["model"] == MODEL
    [run] = agent_runs(agent_log)
    assert "Be terse." in told(run)
    definition = Path(run["env"]["OPENCODE_CONFIG_DIR"]) / "agents" / "canopy-reviewer.md"
    assert f'\nmodel: "{MODEL}"\n' in definition.read_text()


def test_a_model_the_runtime_does_not_list_refuses_the_eval(
    scenario: Scenario,
    commits: tuple[str, str],
    opencode_state: Path,
    agent_log: Path,
) -> None:
    sha, base = commits
    cases(scenario, case("retry", sha, base, "retry.py:1"))
    listed(opencode_state, "acme/another-model")
    printed = scenario.operator("review", "eval", "--model", MODEL, code=1)
    assert "review eval refused: model_missing" in printed.err
    assert agent_runs(agent_log) == []


def test_a_dry_run_shows_the_cases_and_starts_nothing(
    scenario: Scenario,
    commits: tuple[str, str],
    agent_log: Path,
) -> None:
    sha, base = commits
    cases(scenario, case("retry", sha, base, "retry.py:1"), case("elsewhere", sha, base, pr=THEIRS, repo="web"))
    printed = scenario.operator("review", "eval", "--dry-run")
    assert printed.out.startswith("Would review 2 cases, starting nothing now, with prompt `reviewer.md` (canopy's)")
    assert f"  retry      bug    {PR} at {sha[:12]} from {base[:12]} in repo; bug at retry.py:1\n" in printed.out
    assert "; refused, unknown_repo: 'web' is not a repository in this workspace" in printed.out
    assert agent_runs(agent_log) == []
    assert not (scenario.env.state_dir / evals.EVALS_DIR).exists()
    plan = json.loads(scenario.operator("review", "eval", "--dry-run", "--json", "--case", "retry").out)
    assert [c["name"] for c in plan["cases"]] == ["retry"]


def test_an_eval_needs_cases_and_names_only_its_own(scenario: Scenario, commits: tuple[str, str]) -> None:
    printed = scenario.operator("review", "eval", code=1)
    assert "no eval cases: add [[review.eval_cases]] tables" in printed.err
    sha, base = commits
    cases(scenario, case("retry", sha, base, "retry.py:1"))
    printed = scenario.operator("review", "eval", "--case", "other", code=1)
    assert "no eval case named other; the cases are retry" in printed.err


def test_only_the_operator_runs_an_eval(scenario: Scenario, commits: tuple[str, str], agent_log: Path) -> None:
    sha, base = commits
    cases(scenario, case("retry", sha, base, "retry.py:1"))
    with mock.patch.dict(os.environ, {"CANOPY_RUN_ID": "7"}):
        printed = scenario.operator("review", "eval", code=1)
    assert "review eval refused (inside_run)" in printed.err
    assert agent_runs(agent_log) == []
    rows = records.fetch_all(scenario.conn, records.ReviewRun, sql.select("*").from_("review_runs"))
    assert rows == []


def test_status_says_when_no_score_is_of_the_reviewer_as_configured_now(
    scenario: Scenario,
    commits: tuple[str, str],
    opencode_state: Path,
) -> None:
    def said() -> list[str]:
        return [line for line in scenario.operator("status").out.splitlines() if line.startswith("Review eval:")]

    assert said() == []
    sha, base = commits
    cases(scenario, case("retry", sha, base, "retry.py:1"))
    assert said() == ["Review eval: the reviewer has no score on your cases yet; run `canopy review eval` to score it."]
    # An eval that scores no case is no score.
    with reviewer_reports("no result line"):
        scenario.operator("review", "eval")
    assert len(said()) == 1
    with reviewer_reports(CLEAN):
        scenario.operator("review", "eval")
    assert said() == []
    newest = saved(scenario.env)["started_at"][:10]

    (personas_dir(scenario.env) / "terse.md").write_text("Be terse.\n")
    scenario.configures(personas={"reviewer": "terse"}, runtime={"models": {"reviewer": MODEL}})
    overrides = scenario.env.user_file.parent / "prompts"
    overrides.mkdir(exist_ok=True)
    (overrides / "reviewer.md").write_text((resources.prompts_dir() / "reviewer.md").read_text() + "\nBe kind.\n")
    assert said() == [
        (
            f"Review eval: the reviewer's prompt, persona and model changed since its newest score, {newest}; "
            "run `canopy review eval` to score it."
        ),
    ]
    # An eval of something else scores nothing that runs now; one of what runs now does.
    listed(opencode_state, MODEL, "acme/another-model")
    with reviewer_reports(CLEAN):
        scenario.operator("review", "eval", "--model", "acme/another-model")
    assert said() == [
        (
            f"Review eval: the reviewer's model changed since its newest score, {newest}; "
            "run `canopy review eval` to score it."
        ),
    ]
    with reviewer_reports(CLEAN):
        scenario.operator("review", "eval")
    assert said() == []
