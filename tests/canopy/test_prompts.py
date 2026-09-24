import pytest

from canopy import prompts
from canopy.config import load
from tests.conftest import CanopyEnv

VALUES = {
    "KEY": "PROJ-1",
    "SLOT": "/pool/1/repo",
    "BRANCH": "agent/PROJ-1-work",
    "BASE": "main",
    "TRACKER_PROVIDER": "jira",
    "NEEDS_HUMAN_LABEL": "needs-human",
    "PR_LABEL": "agent",
    "TIMEOUT_MINUTES": "45",
}


def test_shipped_implement_prompt_renders_completely(canopy_env: CanopyEnv) -> None:
    text = prompts.render_worker(load(canopy_env.repo, canopy_env.user_file), "implement", VALUES)
    assert "{{" not in text
    assert "}}" not in text
    assert '"branch":"agent/PROJ-1-work"' in text


def test_rendering_is_one_pass(canopy_env: CanopyEnv) -> None:
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text("{{KEY}} {{BRANCH}}\n")
    cfg = load(canopy_env.repo, canopy_env.user_file)
    text = prompts.render_worker(cfg, "implement", {**VALUES, "KEY": "{{BRANCH}}"})
    assert text == "{{BRANCH}} agent/PROJ-1-work\n"


def test_unknown_placeholder_is_an_error(canopy_env: CanopyEnv) -> None:
    cfg = load(canopy_env.repo, canopy_env.user_file)
    with pytest.raises(prompts.PromptError, match=r"unknown placeholder \{\{BASE\}\}"):
        prompts.render_worker(cfg, "implement", {k: v for k, v in VALUES.items() if k != "BASE"})
