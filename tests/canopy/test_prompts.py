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
    "REQUEST": "10234",
    "MAP": "/ws/MAP.md",
    "WORKER_COMMENT": "starts with `CANOPY:` outside any quote",
    "MARK_COMMENTS": "In every comment and reply you post, start it with `CANOPY:` and a space.",
    "OPEN_PR": "Open each PR through the GitHub MCP.",
    "TRUSTED_REVIEWERS": "`octocat`",
    "OPERATOR_MESSAGES": "No messages from the operator.",
    "REVIEW_FINDINGS": "None.",
}
UNIT_KINDS = sorted(k for k in prompts.WORKER if k != "split")


@pytest.mark.parametrize("kind", UNIT_KINDS)
def test_shipped_worker_prompts_render_completely(canopy_env: CanopyEnv, kind: str) -> None:
    text = prompts.render_worker(load(canopy_env.root, canopy_env.user_file), kind, VALUES)
    assert "{{" not in text
    assert "}}" not in text
    assert '"branch":"agent/PROJ-1-work","prs":{"repo":"<url or null>"}' in text
    assert "attempt 1 of 2" in text
    # A joint run's worker learns its repositories from these, so the shipped prompts have them, and every public
    # worker hears the operator's messages (D093).
    prompts.render_worker(load(canopy_env.root, canopy_env.user_file), kind, VALUES, required=prompts.REQUIRED_JOINT)
    prompts.render_worker(load(canopy_env.root, canopy_env.user_file), kind, VALUES, required=prompts.REQUIRED_OPERATOR)
    prompts.render_worker(load(canopy_env.root, canopy_env.user_file), kind, VALUES, required=prompts.REQUIRED_STANDING)


def test_the_shipped_split_prompt_renders_completely(canopy_env: CanopyEnv) -> None:
    cfg = load(canopy_env.root, canopy_env.user_file)
    text = prompts.render_worker(cfg, "split", VALUES, required=prompts.REQUIRED_SPLIT)
    assert "{{" not in text
    assert "Read comment 10234 on PROJ-1." in text
    assert text.rstrip().endswith('"children":{"<child key>":"<repository name>"}}')


def test_a_split_prompt_needs_the_request(canopy_env: CanopyEnv) -> None:
    # The splitter's own check of who asked for the split reads the request; an override without it fails closed.
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-split.md").write_text("Split {{KEY}} over {{REPOSITORIES}} for {{LABELS}}\n")
    cfg = load(canopy_env.root, canopy_env.user_file)
    with pytest.raises(prompts.PromptError, match=r"missing required placeholder \{\{REQUEST\}\}"):
        prompts.render_worker(cfg, "split", VALUES, required=prompts.REQUIRED_SPLIT)


def test_rendering_is_one_pass(canopy_env: CanopyEnv) -> None:
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text("{{KEY}} {{BRANCH}} {{LABELS}}\n")
    cfg = load(canopy_env.root, canopy_env.user_file)
    text = prompts.render_worker(cfg, "implement", {**VALUES, "KEY": "{{BRANCH}}"})
    assert text == "{{BRANCH}} agent/PROJ-1-work `agent-ready-alice`\n"


def test_unknown_placeholder_is_an_error(canopy_env: CanopyEnv) -> None:
    cfg = load(canopy_env.root, canopy_env.user_file)
    with pytest.raises(prompts.PromptError, match=r"unknown placeholder \{\{REPOSITORIES\}\}"):
        prompts.render_worker(cfg, "implement", {k: v for k, v in VALUES.items() if k != "REPOSITORIES"})


@pytest.mark.parametrize("kind", sorted(prompts.WORKER))
def test_worker_prompt_without_the_labels_is_an_error(canopy_env: CanopyEnv, kind: str) -> None:
    # An override from before D051 would drop the worker's own label check; it must not render.
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / prompts.WORKER[kind]).write_text("Work {{KEY}} on {{BRANCH}}\n")
    cfg = load(canopy_env.root, canopy_env.user_file)
    with pytest.raises(prompts.PromptError, match=r"missing required placeholder \{\{LABELS\}\}"):
        prompts.render_worker(cfg, kind, VALUES)


def test_a_joint_run_needs_the_repositories(canopy_env: CanopyEnv) -> None:
    # An override from before joint runs still serves a run in one repository, and fails closed for a joint one.
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text("Work {{KEY}} in {{SLOT}} for {{LABELS}}; PR {{PR_URL}}\n")
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert prompts.render_worker(cfg, "implement", VALUES).startswith("Work PROJ-1 in /pool/1/repo")
    with pytest.raises(prompts.PromptError, match=r"missing required placeholder \{\{REPOSITORIES\}\}, \{\{PRS\}\}"):
        prompts.render_worker(cfg, "implement", VALUES, required=prompts.REQUIRED_JOINT)


def test_the_shipped_reviewer_prompt_renders_completely(canopy_env: CanopyEnv) -> None:
    cfg = load(canopy_env.root, canopy_env.user_file)
    values = {
        "PR_URL": "https://github.com/acme/api/pull/7",
        "SHA": "a" * 40,
        "CHECKOUT": "/state/reviews/1/checkout",
        "RUN_ID": "1",
        "TICKET": "PROJ-1",
        "TRACKER_PROVIDER": "jira",
        "LOW_IMPACT": "Only docs change.",
        "ATTEMPT": "1",
        "MAX_ATTEMPTS": "3",
        "CONTEXT": "None.",
        "TIMEOUT_MINUTES": "20",
        "CONTRACT": "{}",
    }
    text = prompts.render(cfg, prompts.REVIEWER, values, required=prompts.REQUIRED_REVIEWER)
    assert "{{" not in text
    assert "Post nothing anywhere" in text


def test_a_reviewer_override_must_name_the_commit(canopy_env: CanopyEnv) -> None:
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "reviewer.md").write_text("Review {{PR_URL}} in {{CHECKOUT}}\n")
    cfg = load(canopy_env.root, canopy_env.user_file)
    values = {"PR_URL": "u", "CHECKOUT": "c", "SHA": "s", "RUN_ID": "1"}
    with pytest.raises(prompts.PromptError, match=r"missing required placeholder \{\{SHA\}\}$"):
        prompts.render(cfg, prompts.REVIEWER, values, required=prompts.REQUIRED_REVIEWER)


@pytest.mark.parametrize(
    ("prefix", "suffix", "recognized", "instruction"),
    [
        ("CANOPY:", "", "starts with `CANOPY:` outside any quote", "start it with `CANOPY:` and a space,"),
        ("", "-- canopy", "ends with `-- canopy` outside any quote", "end it with `-- canopy`,"),
        (
            "CANOPY:",
            "(canopy)",
            "starts with `CANOPY:` and ends with `(canopy)` outside any quote",
            "start it with `CANOPY:` and a space, and end it with `(canopy)`,",
        ),
    ],
)
def test_comment_marks_name_every_mark_set(prefix: str, suffix: str, recognized: str, instruction: str) -> None:
    # A worker's comment carries every mark set, and is recognized only by all of them (D069).
    assert prompts.worker_comment(prefix, suffix) == recognized
    assert instruction in prompts.mark_comments(prefix, suffix)


@pytest.mark.parametrize("kind", sorted(prompts.WORKER))
def test_shipped_worker_prompts_mark_and_recognize_worker_comments(canopy_env: CanopyEnv, kind: str) -> None:
    # Everything posts as the operator, so a worker's own reply must not read back as feedback or a reply (D069).
    values = {**VALUES, "MARK_COMMENTS": "<mark them>", "WORKER_COMMENT": "<is marked>"}
    text = prompts.render_worker(load(canopy_env.root, canopy_env.user_file), kind, values)
    assert "<mark them>" in text
    # A fix-ci worker reads checks, never a comment that could instruct it, so only the others need to recognize one.
    if kind != "fix-ci":
        assert "a comment that <is marked>" in text


def with_pr_skill(env: CanopyEnv, skill: str) -> None:
    env.write_user(env.user_file.read_text().replace("[runtime]\n", f"[runtime]\npr_skill = '{skill}'\n", 1))


def test_open_pr_names_the_mcp_or_only_the_skill() -> None:
    assert prompts.open_pr("") == "Open each PR through the GitHub MCP."
    text = prompts.open_pr("acme-pr")
    assert "by following the skill `acme-pr`, and in no other way" in text
    # A missing skill fails the run rather than falling back to the MCP the operator set it to avoid.
    assert "report `failed` with a summary that starts `no PR skill:`" in text
    assert "MCP" not in text


@pytest.mark.parametrize(
    ("kind", "before"),
    [("implement", "Never target another branch."), ("resume", "with the ticket key in the\ntitle.")],
)
def test_shipped_prompts_that_open_prs_say_how(canopy_env: CanopyEnv, kind: str, before: str) -> None:
    text = prompts.render_worker(load(canopy_env.root, canopy_env.user_file), kind, {**VALUES, "OPEN_PR": "<how>"})
    assert f"{before} <how>" in text


@pytest.mark.parametrize("kind", prompts.OPENS_PRS)
def test_with_a_pr_skill_an_override_must_say_how_to_open_prs(canopy_env: CanopyEnv, kind: str) -> None:
    # An override that still names the GitHub MCP would open the PRs the skill is set to avoid: fail closed.
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / prompts.WORKER[kind]).write_text("Work {{KEY}} for {{LABELS}}; open a PR through the GitHub MCP\n")
    assert prompts.render_worker(load(canopy_env.root, canopy_env.user_file), kind, VALUES).startswith("Work PROJ-1")
    with_pr_skill(canopy_env, "acme-pr")
    with pytest.raises(prompts.PromptError, match=r"missing required placeholder \{\{OPEN_PR\}\}"):
        prompts.render_worker(load(canopy_env.root, canopy_env.user_file), kind, VALUES)


def test_a_pr_skill_does_not_constrain_kinds_that_open_no_pr(canopy_env: CanopyEnv) -> None:
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-fix-ci.md").write_text("Fix CI on {{KEY}} for {{LABELS}}\n")
    with_pr_skill(canopy_env, "acme-pr")
    text = prompts.render_worker(load(canopy_env.root, canopy_env.user_file), "fix-ci", VALUES)
    assert text == "Fix CI on PROJ-1 for `agent-ready-alice`\n"


def test_shipped_overseer_prompt_reads_the_comment_marks(canopy_env: CanopyEnv) -> None:
    text = prompts.render_overseer(load(canopy_env.root, canopy_env.user_file), "{}")
    assert "## Workers' comments" in text
    assert "`trust.comment_prefix`" in text
    assert "`trust.comment_suffix`" in text


def test_trusted_reviewers_name_canopys_reviewer_in_words_and_say_when_nobody_is() -> None:
    assert prompts.trusted_reviewers(["octocat", "canopy:review"]) == (
        "`octocat`, canopy's own reviewer (its findings come in this prompt, never on the PR)"
    )
    assert prompts.trusted_reviewers([]) == "none (every reviewer's feedback needs the operator's go-ahead)"


def test_shipped_resume_prompts_gate_untrusted_reviewers(canopy_env: CanopyEnv) -> None:
    cfg = load(canopy_env.root, canopy_env.user_file)
    public = prompts.render_worker(cfg, "resume", VALUES)
    assert "Trusted reviewers: `octocat`." in public
    assert "## Messages from the operator\n\nNo messages from the operator.\n" in public
    private = prompts.render_worker(cfg, "resume", {**VALUES, "CONVERSATION": "No messages yet."}, private=True)
    assert "Trusted reviewers: `octocat`." in private
