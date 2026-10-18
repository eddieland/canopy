import re

import pytest

from canopy.core import prompts, vocab
from canopy.core.config import load
from canopy.infra import resources
from tests.canopy.helpers import PROMPT_VALUES, with_rebase
from tests.conftest import CanopyEnv

# A row of the overseer prompt's phase table: `| `phase` | evidence | action |`.
_PHASE_ROW = re.compile(r"^\| `([a-z_]+)` \|", re.MULTILINE)

UNIT_KINDS = sorted(k for k in prompts.WORKER if k not in ("split", "plan"))
# The kinds whose prompt checks the queue label through `{{LABELS}}`: a plan's carries its check in `{{AUTHORIZATION}}`.
LABELED_KINDS = sorted(k for k in prompts.WORKER if k != "plan")


@pytest.mark.parametrize("kind", UNIT_KINDS)
def test_shipped_worker_prompts_render_completely(canopy_env: CanopyEnv, kind: str) -> None:
    text = prompts.render_worker(load(canopy_env.root, canopy_env.user_file), kind, PROMPT_VALUES)
    assert "{{" not in text
    assert "}}" not in text
    assert '"branch":"agent/PROJ-1-work","prs":{"repo":"<url or null>"}' in text
    assert "attempt 1 of 2" in text
    # A joint run's worker learns its repositories from these, so the shipped prompts have them, and every public
    # worker hears the operator's messages (D093).
    prompts.render_worker(
        load(canopy_env.root, canopy_env.user_file), kind, PROMPT_VALUES, required=prompts.REQUIRED_JOINT
    )
    prompts.render_worker(
        load(canopy_env.root, canopy_env.user_file), kind, PROMPT_VALUES, required=prompts.REQUIRED_OPERATOR
    )
    prompts.render_worker(
        load(canopy_env.root, canopy_env.user_file), kind, PROMPT_VALUES, required=prompts.REQUIRED_STANDING
    )


def test_the_shipped_split_prompt_renders_completely(canopy_env: CanopyEnv) -> None:
    cfg = load(canopy_env.root, canopy_env.user_file)
    text = prompts.render_worker(cfg, "split", PROMPT_VALUES, required=prompts.REQUIRED_SPLIT)
    assert "{{" not in text
    assert "Read comment 10234 on PROJ-1." in text
    assert text.rstrip().endswith('"children":{"<child key>":"<repository name>"}}')


@pytest.mark.parametrize("private", [False, True])
def test_the_shipped_plan_prompt_renders_completely(canopy_env: CanopyEnv, *, private: bool) -> None:
    cfg = load(canopy_env.root, canopy_env.user_file)
    values = {
        **PROMPT_VALUES,
        "AUTHORIZATION": prompts.plan_authorization("PROJ-1", ["agent-ready-alice"], private=private),
        "PLAN_FILE": ".canopy-plan.md",
        "PLAN_OUT": ".canopy-new-plan.md",
        "MAX_PLAN_CHARS": "100,000",
        "SLOT": "/ws/desks/PROJ-1",
    }
    text = prompts.render_worker(cfg, "plan", values, private=private)
    assert text.startswith("# canopy worker: plan\n")
    assert "{{" not in text
    assert "If `/ws/desks/PROJ-1/.canopy-plan.md` exists, it is the plan this one replaces." in text
    assert "Write the plan as markdown to `/ws/desks/PROJ-1/.canopy-new-plan.md`" in text
    assert "within 100,000 characters" in text
    assert text.rstrip().endswith(
        '{"status":"done|blocked|failed","summary":"<one paragraph>","question":"<only when blocked>"}'
    )
    if private:
        assert "there is no label to check" in text
    else:
        assert "carries none of the labels `agent-ready-alice`" in text


@pytest.mark.parametrize("missing", prompts.REQUIRED_PLAN)
def test_a_plan_prompt_needs_its_authorization_and_the_operators_messages(canopy_env: CanopyEnv, missing: str) -> None:
    # An override without its own check, or without the reply asking for changes, fails closed.
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    used = " ".join(f"{{{{{name}}}}}" for name in prompts.REQUIRED_PLAN if name != missing)
    (overrides / "worker-plan.md").write_text(f"Plan {{{{KEY}}}}: {used}\n")
    cfg = load(canopy_env.root, canopy_env.user_file)
    values = {**PROMPT_VALUES, "AUTHORIZATION": "check", "PLAN_OUT": ".canopy-new-plan.md"}
    with pytest.raises(prompts.PromptError, match=rf"missing required placeholder \{{\{{{missing}\}}\}}"):
        prompts.render_worker(cfg, "plan", values)


def test_a_split_prompt_needs_the_request(canopy_env: CanopyEnv) -> None:
    # The splitter's own check of who asked for the split reads the request; an override without it fails closed.
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-split.md").write_text("Split {{KEY}} over {{REPOSITORIES}} for {{LABELS}}\n")
    cfg = load(canopy_env.root, canopy_env.user_file)
    with pytest.raises(prompts.PromptError, match=r"missing required placeholder \{\{REQUEST\}\}"):
        prompts.render_worker(cfg, "split", PROMPT_VALUES, required=prompts.REQUIRED_SPLIT)


def test_rendering_is_one_pass(canopy_env: CanopyEnv) -> None:
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text("{{KEY}} {{BRANCH}} {{LABELS}}\n")
    cfg = load(canopy_env.root, canopy_env.user_file)
    text = prompts.render_worker(cfg, "implement", {**PROMPT_VALUES, "KEY": "{{BRANCH}}"})
    assert text == "{{BRANCH}} agent/PROJ-1-work `agent-ready-alice`\n"


def test_unknown_placeholder_is_an_error(canopy_env: CanopyEnv) -> None:
    cfg = load(canopy_env.root, canopy_env.user_file)
    with pytest.raises(prompts.PromptError, match=r"unknown placeholder \{\{REPOSITORIES\}\}"):
        prompts.render_worker(cfg, "implement", {k: v for k, v in PROMPT_VALUES.items() if k != "REPOSITORIES"})


@pytest.mark.parametrize("kind", LABELED_KINDS)
def test_worker_prompt_without_the_labels_is_an_error(canopy_env: CanopyEnv, kind: str) -> None:
    # An override from before D051 would drop the worker's own label check; it must not render.
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / prompts.WORKER[kind]).write_text("Work {{KEY}} on {{BRANCH}}\n")
    cfg = load(canopy_env.root, canopy_env.user_file)
    with pytest.raises(prompts.PromptError, match=r"missing required placeholder \{\{LABELS\}\}"):
        prompts.render_worker(cfg, kind, PROMPT_VALUES)


def test_a_joint_run_needs_the_repositories(canopy_env: CanopyEnv) -> None:
    # An override from before joint runs still serves a run in one repository, and fails closed for a joint one.
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-implement.md").write_text("Work {{KEY}} in {{SLOT}} for {{LABELS}}; PR {{PR_URL}}\n")
    cfg = load(canopy_env.root, canopy_env.user_file)
    assert prompts.render_worker(cfg, "implement", PROMPT_VALUES).startswith("Work PROJ-1 in /pool/1/repo")
    with pytest.raises(prompts.PromptError, match=r"missing required placeholder \{\{REPOSITORIES\}\}, \{\{PRS\}\}"):
        prompts.render_worker(cfg, "implement", PROMPT_VALUES, required=prompts.REQUIRED_JOINT)


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
    text = prompts.render_reviewer(cfg, values)
    assert "{{" not in text
    assert "Post nothing anywhere" in text


def test_a_reviewer_override_must_name_the_commit(canopy_env: CanopyEnv) -> None:
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "reviewer.md").write_text("Review {{PR_URL}} in {{CHECKOUT}}\n")
    cfg = load(canopy_env.root, canopy_env.user_file)
    values = {"PR_URL": "u", "CHECKOUT": "c", "SHA": "s", "RUN_ID": "1"}
    with pytest.raises(prompts.PromptError, match=r"missing required placeholder \{\{SHA\}\}$"):
        prompts.render_reviewer(cfg, values)


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


@pytest.mark.parametrize("kind", LABELED_KINDS)
def test_shipped_worker_prompts_mark_and_recognize_worker_comments(canopy_env: CanopyEnv, kind: str) -> None:
    # Everything posts as the operator, so a worker's own reply must not read back as feedback or a reply (D069).
    values = {**PROMPT_VALUES, "MARK_COMMENTS": "<mark them>", "WORKER_COMMENT": "<is marked>"}
    text = prompts.render_worker(load(canopy_env.root, canopy_env.user_file), kind, values)
    assert "<mark them>" in text
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
    text = prompts.render_worker(
        load(canopy_env.root, canopy_env.user_file), kind, {**PROMPT_VALUES, "OPEN_PR": "<how>"}
    )
    assert f"{before} <how>" in text


@pytest.mark.parametrize("kind", prompts.OPENS_PRS)
def test_with_a_pr_skill_an_override_must_say_how_to_open_prs(canopy_env: CanopyEnv, kind: str) -> None:
    # An override that still names the GitHub MCP would open the PRs the skill is set to avoid: fail closed.
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / prompts.WORKER[kind]).write_text("Work {{KEY}} for {{LABELS}}; open a PR through the GitHub MCP\n")
    assert prompts.render_worker(load(canopy_env.root, canopy_env.user_file), kind, PROMPT_VALUES).startswith(
        "Work PROJ-1"
    )
    with_pr_skill(canopy_env, "acme-pr")
    with pytest.raises(prompts.PromptError, match=r"missing required placeholder \{\{OPEN_PR\}\}"):
        prompts.render_worker(load(canopy_env.root, canopy_env.user_file), kind, PROMPT_VALUES)


def test_a_pr_skill_does_not_constrain_kinds_that_open_no_pr(canopy_env: CanopyEnv) -> None:
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / "worker-split.md").write_text("Split {{KEY}} for {{LABELS}} in {{REPOSITORIES}} as {{REQUEST}}\n")
    with_pr_skill(canopy_env, "acme-pr")
    text = prompts.render_worker(
        load(canopy_env.root, canopy_env.user_file), "split", PROMPT_VALUES, required=prompts.REQUIRED_SPLIT
    )
    assert text.startswith("Split PROJ-1 for `agent-ready-alice` in ")


def with_trailer(env: CanopyEnv, name: str, email: str) -> None:
    env.append_user(f'\n[trust]\ncommit_trailer_name = "{name}"\ncommit_trailer_email = "{email}"\n')


def without_trailer(env: CanopyEnv) -> None:
    env.append_user("\n[trust]\ncommit_trailer = false\n")


@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("kind", prompts.COMMITS)
def test_shipped_prompts_that_commit_name_the_configured_trailer(
    canopy_env: CanopyEnv, kind: str, *, private: bool
) -> None:
    values = {**PROMPT_VALUES, "CONVERSATION": "None."}
    text = prompts.render_worker(load(canopy_env.root, canopy_env.user_file), kind, values, private=private)
    assert "`Co-authored-by: canopy worker <noreply@canopy.invalid>`" in text
    with_trailer(canopy_env, "Acme Agent", "agent@acme.test")
    text = prompts.render_worker(load(canopy_env.root, canopy_env.user_file), kind, values, private=private)
    assert "`Co-authored-by: Acme Agent <agent@acme.test>`" in text
    assert "canopy.invalid" not in text


@pytest.mark.parametrize("kind", prompts.COMMITS)
def test_with_a_custom_trailer_an_override_must_name_it(canopy_env: CanopyEnv, kind: str) -> None:
    # An override that still spells out the default trailer would credit commits to it: fail closed.
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / prompts.WORKER[kind]).write_text("Work {{KEY}} for {{LABELS}}; add the canopy worker trailer\n")
    assert prompts.render_worker(load(canopy_env.root, canopy_env.user_file), kind, PROMPT_VALUES).startswith(
        "Work PROJ-1"
    )
    with_trailer(canopy_env, "Acme Agent", "agent@acme.test")
    with pytest.raises(
        prompts.PromptError, match=r"missing required placeholder \{\{COMMIT_ATTRIBUTION\}\} or \{\{COMMIT_TRAILER\}\}"
    ):
        prompts.render_worker(load(canopy_env.root, canopy_env.user_file), kind, PROMPT_VALUES)


@pytest.mark.parametrize("kind", prompts.COMMITS)
def test_with_a_custom_trailer_an_older_override_naming_it_still_renders(canopy_env: CanopyEnv, kind: str) -> None:
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / prompts.WORKER[kind]).write_text("Work {{KEY}} for {{LABELS}}; add `{{COMMIT_TRAILER}}`\n")
    with_trailer(canopy_env, "Acme Agent", "agent@acme.test")
    text = prompts.render_worker(load(canopy_env.root, canopy_env.user_file), kind, PROMPT_VALUES)
    assert text.endswith("add `Co-authored-by: Acme Agent <agent@acme.test>`\n")


@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("kind", prompts.COMMITS)
def test_with_the_trailer_off_shipped_prompts_add_none(canopy_env: CanopyEnv, kind: str, *, private: bool) -> None:
    without_trailer(canopy_env)
    values = {**PROMPT_VALUES, "CONVERSATION": "None."}
    text = prompts.render_worker(load(canopy_env.root, canopy_env.user_file), kind, values, private=private)
    assert "Co-authored-by" not in text
    assert (
        "Keep the agent runtime's attribution trailer on commits, if it adds one, and add no co-author trailer." in text
    )


@pytest.mark.parametrize("kind", prompts.COMMITS)
def test_with_the_trailer_off_an_override_must_carry_the_attribution(canopy_env: CanopyEnv, kind: str) -> None:
    # An older override that adds the trailer itself would keep adding the one the operator turned off: fail closed.
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / prompts.WORKER[kind]).write_text("Work {{KEY}} for {{LABELS}}; add `{{COMMIT_TRAILER}}`\n")
    without_trailer(canopy_env)
    with pytest.raises(prompts.PromptError, match=r"missing required placeholder \{\{COMMIT_ATTRIBUTION\}\}$"):
        prompts.render_worker(load(canopy_env.root, canopy_env.user_file), kind, PROMPT_VALUES)
    (overrides / prompts.WORKER[kind]).write_text("Work {{KEY}} for {{LABELS}}. {{COMMIT_ATTRIBUTION}}\n")
    assert "add no co-author trailer" in prompts.render_worker(
        load(canopy_env.root, canopy_env.user_file), kind, PROMPT_VALUES
    )


def test_the_trailer_off_does_not_constrain_a_split(canopy_env: CanopyEnv) -> None:
    without_trailer(canopy_env)
    prompts.render_worker(
        load(canopy_env.root, canopy_env.user_file), "split", PROMPT_VALUES, required=prompts.REQUIRED_SPLIT
    )


def test_a_custom_trailer_does_not_constrain_a_split(canopy_env: CanopyEnv) -> None:
    with_trailer(canopy_env, "Acme Agent", "agent@acme.test")
    prompts.render_worker(
        load(canopy_env.root, canopy_env.user_file), "split", PROMPT_VALUES, required=prompts.REQUIRED_SPLIT
    )


@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("kind", prompts.COMMITS)
def test_shipped_prompts_that_commit_say_how_to_bring_a_base_in(
    canopy_env: CanopyEnv, kind: str, *, private: bool
) -> None:
    values = {**PROMPT_VALUES, "CONVERSATION": "None."}
    text = prompts.render_worker(load(canopy_env.root, canopy_env.user_file), kind, values, private=private)
    assert "merge `origin/<base>` into it. Never rebase" in text
    assert "--force-with-lease" not in text
    with_rebase(canopy_env)
    text = prompts.render_worker(load(canopy_env.root, canopy_env.user_file), kind, values, private=private)
    assert "rebase onto `origin/<base>`, and never merge it in" in text
    assert "`git push --force-with-lease origin HEAD:refs/heads/agent/PROJ-1-work`" in text
    assert "Never rebase" not in text


@pytest.mark.parametrize("kind", prompts.COMMITS)
def test_with_rebase_an_override_must_say_how_to_bring_a_base_in(canopy_env: CanopyEnv, kind: str) -> None:
    # An override written for merging would make the merge commits the operator's repositories refuse: fail closed.
    overrides = canopy_env.user_file.parent / "prompts"
    overrides.mkdir()
    (overrides / prompts.WORKER[kind]).write_text("Work {{KEY}} for {{LABELS}}; merge the base in\n")
    assert prompts.render_worker(load(canopy_env.root, canopy_env.user_file), kind, PROMPT_VALUES).startswith(
        "Work PROJ-1"
    )
    with_rebase(canopy_env)
    with pytest.raises(prompts.PromptError, match=r"missing required placeholder \{\{BRANCH_UPDATE\}\}"):
        prompts.render_worker(load(canopy_env.root, canopy_env.user_file), kind, PROMPT_VALUES)


def test_rebase_does_not_constrain_a_split(canopy_env: CanopyEnv) -> None:
    with_rebase(canopy_env)
    prompts.render_worker(
        load(canopy_env.root, canopy_env.user_file), "split", PROMPT_VALUES, required=prompts.REQUIRED_SPLIT
    )


def test_shipped_overseer_prompt_reads_the_comment_marks(canopy_env: CanopyEnv) -> None:
    text = prompts.prompt_path(load(canopy_env.root, canopy_env.user_file), prompts.OVERSEER).read_text()
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
    public = prompts.render_worker(cfg, "resume", PROMPT_VALUES)
    assert "Trusted reviewers: `octocat`." in public
    assert "## Messages from the operator\n\nNo messages from the operator.\n" in public
    private = prompts.render_worker(cfg, "resume", {**PROMPT_VALUES, "CONVERSATION": "No messages yet."}, private=True)
    assert "Trusted reviewers: `octocat`." in private


def test_ticket_set_accepts_every_phase_in_the_overseer_prompts_table() -> None:
    """The overseer records the phases its table names, so `ticket set --phase` must take each one."""
    text = (resources.prompts_dir() / prompts.OVERSEER).read_text()
    table = text.split("## Phase table", 1)[1].split("\n## ", 1)[0]
    phases = _PHASE_ROW.findall(table)
    assert phases
    assert sorted(phases) == sorted(vocab.Phase)
    # The table says the phases from `pushed_no_pr` to `merged` are a unit's; the CLI then requires --repo for them.
    unit = phases[phases.index("pushed_no_pr") : phases.index("merged") + 1]
    assert set(unit) == vocab.UNIT_PHASES


def test_every_run_kind_has_a_worker_prompt_and_every_kind_but_split_and_plan_a_private_one() -> None:
    # A split never runs for a private ticket, and a plan's one prompt serves both (DESIGN §22, §25). `fix-ci` is
    # dispatched no more, and its prompts went with it (DESIGN §8).
    dispatched = set(vocab.RunKind) - {vocab.RunKind.FIX_CI}
    assert set(prompts.WORKER) == dispatched
    assert set(prompts.WORKER_PRIVATE) == dispatched - {vocab.RunKind.SPLIT, vocab.RunKind.PLAN}
    shipped = {p.name for p in resources.prompts_dir().iterdir()}
    assert shipped.isdisjoint(prompts.RETIRED_WORKER)


def test_a_resume_names_each_of_its_reasons_in_the_vocabularys_order() -> None:
    note = prompts.reasons_note(["review", "ci"], private=False)
    assert note.splitlines() == [
        '- `ci`: checks failed on the PR: fix them, as "Failed checks" below says.',
        (
            "- `review`: review comments, or canopy's review findings, to address, as \"canopy's review\" and "
            '"Reviewers" below say.'
        ),
    ]
    # A private ticket's reply is the operator's, in its conversation; every reason has its line.
    assert "message id in the conversation above" in prompts.reasons_note(["reply"], private=True)
    assert len(prompts.reasons_note(list(vocab.ResumeReason), private=False).splitlines()) == len(vocab.ResumeReason)
    assert prompts.reasons_note([], private=False) == "None named: the context below says why."
