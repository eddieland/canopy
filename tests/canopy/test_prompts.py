import pytest

from canopy.core import prompts
from canopy.core.config import load
from tests.conftest import CanopyEnv

VALUES = {
    "KEY": "PROJ-1",
    "SLOT": "/pool/1/repo",
    "BRANCH": "agent/PROJ-1-work",
    "BASE": "main",
    "STACKING": "This ticket is not stacked on another ticket's branch.",
    "TRACKER_PROVIDER": "jira",
    "NEEDS_HUMAN_LABEL": "needs-human",
    "PR_LABEL": "agent",
    "TIMEOUT_MINUTES": "45",
    "ATTEMPT": "1",
    "MAX_ATTEMPTS": "2",
    "PR_URL": "https://example.test/pr/1",
    "REPOSITORIES": "This run works in one repository:\n- `repo` at `/pool/1/repo`: branch `agent/PROJ-1-work`",
    "PRS": '{"repo":"<url or null>"}',
    "CONTEXT": "None.",
    "AUTHORIZED_REPLIERS": "`alice`",
    "LABELS": "`agent-ready-alice`",
}


@pytest.mark.parametrize("kind", sorted(prompts.WORKER))
def test_shipped_worker_prompts_render_completely(canopy_env: CanopyEnv, kind: str) -> None:
    text = prompts.render_worker(load(canopy_env.repo, canopy_env.user_file), kind, VALUES)
    assert "{{" not in text
    assert "}}" not in text
    assert '"branch":"agent/PROJ-1-work","prs":{"repo":"<url or null>"}' in text
    assert "attempt 1 of 2" in text
    # A joint run's worker learns its repositories from these, so the shipped prompts have them.
    prompts.render_worker(load(canopy_env.repo, canopy_env.user_file), kind, VALUES, required=prompts.REQUIRED_JOINT)


def test_rendering_is_one_pass(canopy_env: CanopyEnv) -> None:
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text("{{KEY}} {{BRANCH}} {{LABELS}}\n")
    cfg = load(canopy_env.repo, canopy_env.user_file)
    text = prompts.render_worker(cfg, "implement", {**VALUES, "KEY": "{{BRANCH}}"})
    assert text == "{{BRANCH}} agent/PROJ-1-work `agent-ready-alice`\n"


def test_unknown_placeholder_is_an_error(canopy_env: CanopyEnv) -> None:
    cfg = load(canopy_env.repo, canopy_env.user_file)
    with pytest.raises(prompts.PromptError, match=r"unknown placeholder \{\{REPOSITORIES\}\}"):
        prompts.render_worker(cfg, "implement", {k: v for k, v in VALUES.items() if k != "REPOSITORIES"})


@pytest.mark.parametrize("kind", sorted(prompts.WORKER))
def test_worker_prompt_without_the_labels_is_an_error(canopy_env: CanopyEnv, kind: str) -> None:
    # An override from before D051 would drop the worker's own label check; it must not render.
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / prompts.WORKER[kind]).write_text("Work {{KEY}} on {{BRANCH}}\n")
    cfg = load(canopy_env.repo, canopy_env.user_file)
    with pytest.raises(prompts.PromptError, match=r"missing required placeholder \{\{LABELS\}\}"):
        prompts.render_worker(cfg, kind, VALUES)


def test_a_joint_run_needs_the_repositories(canopy_env: CanopyEnv) -> None:
    # An override from before joint runs still serves a run in one repository, and fails closed for a joint one.
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text("Work {{KEY}} in {{SLOT}} for {{LABELS}}; PR {{PR_URL}}\n")
    cfg = load(canopy_env.repo, canopy_env.user_file)
    assert prompts.render_worker(cfg, "implement", VALUES).startswith("Work PROJ-1 in /pool/1/repo")
    with pytest.raises(prompts.PromptError, match=r"missing required placeholder \{\{REPOSITORIES\}\}, \{\{PRS\}\}"):
        prompts.render_worker(cfg, "implement", VALUES, required=prompts.REQUIRED_JOINT)
