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
    "CONTEXT": "None.",
    "AUTHORIZED_REPLIERS": "`alice`",
    "LABELS": "`agent-ready-alice`",
    # A split's own: it works in no slot and on no branch (DESIGN §18).
    "WORKSPACE": "/work/acme",
    "REPOS": "- `api`, cloned at `/work/acme/repos/api`: The API.",
    "MAP": "`/work/acme/MAP.md`",
    "REQUEST": "`10234`",
}
SPLIT_ONLY = ("WORKSPACE", "REPOS", "MAP", "REQUEST")
BRANCH_ONLY = ("SLOT", "BRANCH", "BASE", "STACKING", "NEEDS_HUMAN_LABEL", "PR_LABEL", "PR_URL")


@pytest.mark.parametrize("kind", sorted(prompts.WORKER))
def test_shipped_worker_prompts_render_completely(canopy_env: CanopyEnv, kind: str) -> None:
    # Dispatch renders each prompt with only its kind's placeholders, so a split prompt must not use a branch's.
    unused = BRANCH_ONLY if kind == "split" else SPLIT_ONLY
    values = {k: v for k, v in VALUES.items() if k not in unused}
    text = prompts.render_worker(load(canopy_env.repo, canopy_env.user_file), kind, values)
    # No placeholder is left. The split's result line ends in `}}` legitimately: `children` is an object.
    assert "{{" not in text
    assert "attempt 1 of 2" in text
    if kind == "split":
        assert '"children":{' in text
        assert "/work/acme/repos/api" in text
    else:
        assert "}}" not in text
        assert '"branch":"agent/PROJ-1-work"' in text


def test_rendering_is_one_pass(canopy_env: CanopyEnv) -> None:
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text("{{KEY}} {{BRANCH}} {{LABELS}}\n")
    cfg = load(canopy_env.repo, canopy_env.user_file)
    text = prompts.render_worker(cfg, "implement", {**VALUES, "KEY": "{{BRANCH}}"})
    assert text == "{{BRANCH}} agent/PROJ-1-work `agent-ready-alice`\n"


def test_unknown_placeholder_is_an_error(canopy_env: CanopyEnv) -> None:
    cfg = load(canopy_env.repo, canopy_env.user_file)
    with pytest.raises(prompts.PromptError, match=r"unknown placeholder \{\{BASE\}\}"):
        prompts.render_worker(cfg, "implement", {k: v for k, v in VALUES.items() if k != "BASE"})


@pytest.mark.parametrize("kind", sorted(prompts.WORKER))
def test_worker_prompt_without_the_labels_is_an_error(canopy_env: CanopyEnv, kind: str) -> None:
    # An override from before D051 would drop the worker's own label check; it must not render.
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / prompts.WORKER[kind]).write_text("Work {{KEY}} on {{BRANCH}}\n")
    cfg = load(canopy_env.repo, canopy_env.user_file)
    with pytest.raises(prompts.PromptError, match=r"missing required placeholder \{\{LABELS\}\}"):
        prompts.render_worker(cfg, kind, VALUES)


def test_a_split_prompt_without_the_request_is_an_error(canopy_env: CanopyEnv) -> None:
    # The splitter checks the authorized comment that asked for the split; an override that drops it must not render.
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / prompts.WORKER["split"]).write_text("Split {{KEY}} for {{LABELS}}\n")
    cfg = load(canopy_env.repo, canopy_env.user_file)
    with pytest.raises(prompts.PromptError, match=r"missing required placeholder \{\{REQUEST\}\}"):
        prompts.render_worker(cfg, "split", VALUES)
