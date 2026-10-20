"""Prompt files and their overrides: the overseer's prompt (DESIGN §6) and worker prompts (DESIGN §8).

A prompt named `overseer.md` is read from `paths.prompt_overrides` if a file of that name is there, otherwise from the
prompts canopy ships. The overseer's goes into its agent definition (`canopy.runtime.definitions`, DESIGN §13), not a
tick's message, and its only placeholders are for its standing instructions. Worker prompts name their inputs as
`{{NAME}}` placeholders.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from canopy.core.config import CANOPY_REVIEWER, DEFAULT_TRAILER_EMAIL, DEFAULT_TRAILER_NAME
from canopy.core.vocab import ResumeReason, RunKind
from canopy.infra import resources

if TYPE_CHECKING:
    from canopy.core.config import Config

OVERSEER = "overseer.md"
WORKER: dict[str, str] = {
    RunKind.IMPLEMENT: "worker-implement.md",
    RunKind.RESUME: "worker-resume.md",
    RunKind.PLAN: "worker-plan.md",
}
# A private ticket's worker prompts (DESIGN §22): no label check, since the harness checked the start record, and
# nothing written to the ticket. Each must carry the conversation, the only way the worker hears the operator's replies;
# an override without it would run without them.
WORKER_PRIVATE: dict[str, str] = {
    RunKind.IMPLEMENT: "worker-implement-private.md",
    RunKind.RESUME: "worker-resume-private.md",
}
#: A feedback plan's prompt (DESIGN §32), one for a public ticket and a started one alike, as a plan's. Apart from
#: `WORKER`, whose kinds each work a branch.
FEEDBACK_PLAN = "worker-feedback-plan.md"
#: Placeholders a feedback plan's prompt must use: a plan's, and the file in its desk holding its PRs' items, without
#: which it plans from nothing.
REQUIRED_FEEDBACK_PLAN = ("REPOSITORIES", "AUTHORIZATION", "OPERATOR_MESSAGES", "PLAN_OUT", "ITEMS_FILE")
# The prompts of `fix-ci`, a kind a `resume` with the reason `ci` replaced (DESIGN §8). An override of either would be
# read by nothing, so while one exists every `resume` refuses to render (`retired_overrides`) rather than drop the
# operator's CI instructions silently.
RETIRED_WORKER = ("worker-fix-ci.md", "worker-fix-ci-private.md")
# What each reason a `resume` runs for asks of its worker, for `{{REASONS}}` (DESIGN §8). A private ticket's reply is
# the operator's, in its conversation.
_REASON_TEXT: dict[ResumeReason, str] = {
    ResumeReason.CI: 'checks failed on the PR: fix them, as "Failed checks" below says.',
    ResumeReason.REVIEW: (
        'review comments, or canopy\'s review findings, to address, as "canopy\'s review" and "Reviewers" below say.'
    ),
    ResumeReason.REPLY: (
        "an authorized human's reply to a question asked earlier, by comment id or link on the ticket, or the "
        "operator's message above, possibly about review comments to address."
    ),
    ResumeReason.CONFLICT: 'the PR conflicts with its base branch: bring that base in, as "Repositories" above says.',
    ResumeReason.NO_PR: 'the branch is pushed and has no PR: open it, as "Obligations" below says.',
    ResumeReason.RETARGET: (
        "the PR this ticket was stacked on has merged: retarget this ticket's PR to its repository's base branch, as "
        '"Repositories" above says.'
    ),
}
_PRIVATE_REPLY = (
    "the operator's reply, by message id in the conversation above, possibly about review comments to address."
)
REQUIRED_PRIVATE = ("CONVERSATION",)
# A public ticket's worker hears the operator's replies only from these (D093). An override written before they existed
# still serves a ticket the operator never replied to; once there is a reply, it fails to render instead of dropping it.
REQUIRED_OPERATOR = ("OPERATOR_MESSAGES",)
# Placeholders an implement's or a resume's prompt must use once the ticket has an approved plan (DESIGN §25): an older
# override would otherwise run the work without the plan the operator approved for it.
REQUIRED_PLAN_COPY = ("PLAN",)
_PLACEHOLDER_RE = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")
# Placeholders every worker prompt must use. `LABELS` carries the worker's own authorization check (D051); an override
# written before it existed would silently drop that check, so it fails to render instead.
REQUIRED_WORKER = ("LABELS",)
# Placeholders a joint run's prompt must also use: its worker learns its repositories and the result's `prs` from them
# (DESIGN §18). A prompt without them still serves a run in one repository.
REQUIRED_JOINT = ("REPOSITORIES", "PRS")
# Placeholders a plan's prompt must use (DESIGN §25), for a public ticket and a private one alike: its repositories, the
# planner's own authorization check, which names the queue labels on a public ticket (D051), the operator's messages,
# which carry a reply asking for changes to the plan it replaces, and the file the plan is written to, without which
# no plan is ever recorded.
REQUIRED_PLAN = ("REPOSITORIES", "AUTHORIZATION", "OPERATOR_MESSAGES", "PLAN_OUT")
# The kinds whose workers open PRs. With `runtime.pr_skill` set, their prompts must say how, through `{{OPEN_PR}}`: an
# override that still names the GitHub MCP would open the PRs the operator set the skill to avoid.
OPENS_PRS = (RunKind.IMPLEMENT, RunKind.RESUME)
REQUIRED_PR_SKILL = ("OPEN_PR",)
# The reviewer's prompt (DESIGN §21). An override must still name the PR, the commit, and the checkout it reviews.
REVIEWER = "reviewer.md"
REQUIRED_REVIEWER = ("PR_URL", "SHA", "CHECKOUT")
# A resume for a canopy review's findings must carry them: they are in the journal and nowhere else (D114). An
# override written before they existed still serves every other resume.
REQUIRED_REVIEW = ("REVIEW_FINDINGS",)
#: Where a prompt takes the operator's standing instructions to its role (DESIGN §12): the whole section, its heading,
#: the text, and how to read it (`STANDING_FRAMING`), or nothing when none are set, so a run reads no empty section. It
#: starts with the blank line before its heading, so it ends the paragraph before it, as `{{WORKSPACE_LESSONS}}` does.
STANDING_SECTION = "STANDING_SECTION"
#: The placeholder that held the instructions' text alone, or `None.`, before `STANDING_SECTION`. An override written
#: then still renders with it.
STANDING_TEXT = "STANDING_INSTRUCTIONS"
# A prompt must carry one of them once its role's file is set, so an override written before either existed still
# serves an operator who sets none, and fails to render instead of dropping them once one is set. They are in every
# run's prompt, so they are bounded.
REQUIRED_STANDING = (STANDING_SECTION, STANDING_TEXT)
MAX_STANDING_BYTES = 4096
STANDING_HEADING = "## Standing instructions from the operator"
#: Whose standing instructions a prompt carries, which says how to read them (`STANDING_FRAMING`).
Reader = Literal["overseer", "worker", "private", "planner", "reviewer", "chore"]
#: How each reader is told to read the operator's standing instructions, after them in the section.
STANDING_FRAMING: Mapping[Reader, str] = {
    "overseer": (
        "The operator set these in canopy for the overseer, not on a ticket. They are instructions from the operator, "
        "as if they had said them to you, except where one conflicts with anything above: the prompt comes first, and "
        "the CLI's limits hold whatever they say. They are yours, not the workers': never pass them on in `--context`."
    ),
    "worker": (
        "The operator set these in canopy for every worker, not on the ticket. They are instructions from the "
        "operator, as if they had said them to you, except where one conflicts with an obligation below or anything "
        "else this prompt requires: the prompt comes first. They reach nobody else: never quote, paraphrase, or "
        "mention them on the ticket, a PR, or in a commit message."
    ),
    "private": (
        "The operator set these in canopy for every worker. They are instructions from the operator too, as if they "
        "had said them to you, except where one conflicts with an obligation below or anything else this prompt "
        "requires: the prompt comes first. Never quote, paraphrase, or mention them in a PR or a commit message."
    ),
    "planner": (
        "The operator set these in canopy for every worker. They are instructions from the operator too, as if they "
        "had said them to you, except where one conflicts with an obligation below or anything else this prompt "
        "requires: the prompt comes first. Plan the work so that the worker who follows the plan can keep them."
    ),
    "reviewer": (
        "The operator set these in canopy for every review, not for this PR. They are instructions from the operator, "
        "as if they had said them to you, except where one conflicts with anything else this prompt requires: the "
        "prompt comes first. They never let you change, approve, or post anything."
    ),
    "chore": (
        "The operator set these in canopy for every chore, not for this one. Follow them as you follow the text "
        "above, except where one conflicts with it or with the `## Run` section below: those come first."
    ),
}
#: The persona every planner, reviewer, and worker run gets for `{{PERSONA}}` (DESIGN §31): canopy's own voice, which
#: the shipped prompts no longer hold, placed below their obligations. Not required: an override without the placeholder
#: still serves a run whose persona is this one, and keeps whatever voice the override already holds.
DEFAULT_PERSONA = "canopy"
# The operator's notice to workers (`canopy notice`, DESIGN §8), in every prompt that builds, tests, or reads CI: every
# worker's, and the reviewer's. An override written before notices existed still serves while none is in force; while
# one is, it fails to render (`bad_prompt`) instead of dropping it, and `canopy notice` names it.
REQUIRED_NOTICE = ("NOTICE",)
# The operator's notes on a review request reach its reviewer through `{{NOTES}}`; a reviewer's override without it
# still serves every review with none, and fails to render one with notes rather than drop them.
REQUIRED_NOTES = ("NOTES",)
# The kinds whose workers commit, and how their commits are attributed (TRUST_MODEL T5). The shipped prompts carry
# `{{COMMIT_ATTRIBUTION}}`, the whole instruction; an older override may carry `{{COMMIT_TRAILER}}`, the trailer alone,
# or neither. Neither still serves an operator who keeps the default trailer; once `trust.commit_trailer_name` or
# `trust.commit_trailer_email` is changed, a prompt needs one of the two, so it cannot name the old trailer; and once
# `trust.commit_trailer` is off, it needs `{{COMMIT_ATTRIBUTION}}`, so it cannot keep adding one.
COMMITS = (RunKind.IMPLEMENT, RunKind.RESUME)
REQUIRED_TRAILER = ("COMMIT_ATTRIBUTION", "COMMIT_TRAILER")
REQUIRED_NO_TRAILER = ("COMMIT_ATTRIBUTION",)
# How the workers that commit bring a base branch in: merge it, or with `trust.rebase`, rebase and push with a lease
# (DESIGN §8). An override written before it existed says to merge, which still serves an operator who keeps the
# default; once `trust.rebase` is set, it fails to render instead of making the merge commits the operator's
# repositories refuse.
REQUIRED_REBASE = ("BRANCH_UPDATE",)
# Agent memory's placeholders (DESIGN §28): a ticket's notes, the operator's lessons, and the result fields memory adds.
# Each renders as the empty string while its tier is off; the shipped prompts place them so that leaves nothing.
MEMORY_PARTS = ("TICKET_MEMORY", "WORKSPACE_LESSONS", "MEMORY_CONTRACT")
# The prompt files that carry `{{NOTICE}}`, and the run kinds each serves: every worker's, public and private, the
# planner's, and the reviewer's.
_HEARS_NOTICE: dict[str, list[str]] = {
    **{WORKER[k]: [str(k)] for k in WORKER_PRIVATE},
    **{WORKER_PRIVATE[k]: [f"{k} (private)"] for k in WORKER_PRIVATE},
    WORKER[RunKind.PLAN]: [str(RunKind.PLAN)],
    FEEDBACK_PLAN: [str(RunKind.FEEDBACK_PLAN)],
    REVIEWER: ["review"],
}


def worker_comment(prefix: str, suffix: str) -> str:
    """Return how a worker's comment is recognized (D069), to follow "a comment that": it carries every mark set.

    Marks inside a quote do not count, so a human's reply that quotes a worker's comment stays the human's.
    """
    marks = [f"starts with `{prefix}`"] if prefix else []
    if suffix:
        marks.append(f"ends with `{suffix}`")
    return f"{' and '.join(marks)} outside any quote"


def plan_authorization(key: str, labels: Sequence[str], *, private: bool) -> str:
    """Return the planner's `{{AUTHORIZATION}}`: the label check on a public ticket, or why a private one has none.

    The planner writes nothing anywhere, so a plan it should not have written costs only its spend; the check keeps the
    rule every worker follows (D051). A private ticket's start record was checked by the harness (DESIGN §22).
    """
    if private:
        return (
            f"The operator started {key} in canopy, which authorized this run; there is no label to check. Its "
            "conversation stays with the operator."
        )
    named = ", ".join(f"`{label}`" for label in labels)
    return (
        f"Before any other work, read {key} through the tracker. If it is closed, or carries none of the labels "
        f"{named}, the overseer should not have dispatched you: write no plan, and report `failed` with a summary that "
        "starts `not authorized:` and says which it was."
    )


def follow_ups(
    key: str, limit: int, repos: Sequence[str], *, needs_human: str, labels: Sequence[str], private: bool = False
) -> str:
    """Return a worker's `{{FOLLOW_UPS}}` when it may file follow-up tickets (DESIGN §18): what one is, and how.

    A follow-up is a request: it authorizes nothing, and canopy works it only once the operator labels or starts it. A
    request to split the ticket is the one time its own work is filed as follow-ups (M46). A private ticket's worker
    files them too, the one thing it writes to the tracker: its version says that a follow-up is public all the same,
    and that it lists them in its summary, since it comments nowhere.

    Returns:
        The instructions, the bound, the repositories a follow-up may name, and the result field that reports them.
    """
    names = ", ".join(f"`{r}`" for r in repos)
    queue = ", ".join(f"`{label}`" for label in labels)
    asker = "the operator" if private else "an authorized replier or the operator"
    if private:
        listed = (
            "Creating them is the one thing you write to the tracker: no comment on any ticket, and no edit to "
            f"{key} or to any other ticket, though the tool that creates tickets may be able to. A follow-up is read "
            f"by everyone who reads the tracker, while {key}'s conversation stays private: its title and body describe "
            "the work in your own words, and carry nothing from the operator's messages, the conversation, or the "
            "plan. Your summary lists the follow-ups you filed."
        )
    else:
        listed = f"Your comment on {key} lists the follow-ups you filed."
    return (
        "You may file follow-up tickets: work outside this ticket that you found while doing it, such as a TODO your "
        "change leaves, a fix you saw and did not make, or a next step the change makes possible. Do this ticket's "
        f"own work yourself, never as a follow-up, unless {asker} asked for {key} to be split into separate tickets: "
        "then file each part the request names as a follow-up, and do only what it leaves to this ticket, if "
        f"anything. File at most {limit}, and none for work that is already a ticket."
        "\n\n"
        f"Create each in {key}'s project through the tracker, linked to {key} as its parent the way the tracker skill "
        f"says, with no assignee and no labels: never one of {queue}, and never `{needs_human}`. Its body says what it "
        "covers, as a description of the work rather than instructions to an agent, and, when one repository "
        f"applies, names it on a line of its own, `canopy-repo: <name>`, one of {names}. A follow-up that must land "
        f"after another ticket, this one included, gets the tracker's blocker relation. {listed}\n\n"
        "A follow-up is a request, not work you start: canopy asks the operator about each one, and works it only once "
        "they label it or start it, as any ticket. Name every ticket you created in your result line's object, also "
        'when you report `blocked` or `failed`: `"created":{"<key>":"<repository or null>"}`, each with the repository '
        "its body names, or null when it names none. Leave the field out when you created none."
    )


def no_follow_ups(why: str) -> str:
    """Return a worker's `{{FOLLOW_UPS}}` when it may file none (DESIGN §18), saying `why`."""
    return (
        f"File no tickets in the tracker: {why}. Say in your summary what you found that is outside this ticket, for "
        "the operator to file."
    )


def trusted_reviewers(reviewers: Sequence[str]) -> str:
    """Return the worker's list of trusted reviewers (DESIGN §7, D089), naming canopy's own reviewer in words."""
    names = [
        "canopy's own reviewer (its findings come in this prompt, never on the PR)"
        if r == CANOPY_REVIEWER
        else f"`{r}`"
        for r in reviewers
    ]
    return ", ".join(names) if names else "none (every reviewer's feedback needs the operator's go-ahead)"


def reasons_note(reasons: Sequence[str], *, private: bool) -> str:
    """Return a resume's `{{REASONS}}`: why it runs, a line for each reason its dispatch named (DESIGN §8).

    The overseer's context points at what to read for each; the prompt's sections say how to work each one.

    Returns:
        A line per reason, in the vocabulary's order, or a line saying none was named.
    """
    named = [r for r in ResumeReason if r in reasons]
    if not named:
        return "None named: the context below says why."
    return "\n".join(
        f"- `{r}`: {_PRIVATE_REPLY if private and r is ResumeReason.REPLY else _REASON_TEXT[r]}" for r in named
    )


def retired_overrides(config: Config) -> list[Path]:
    """Return the operator's overrides of the retired `fix-ci` prompts, which refuse every `resume` while they exist.

    Returns:
        Each such override's path, in `RETIRED_WORKER`'s order.
    """
    return [
        config.paths.prompt_overrides / name
        for name in RETIRED_WORKER
        if (config.paths.prompt_overrides / name).is_file()
    ]


def plan_note(copy: Path | None, outline: Sequence[str]) -> str:
    """Return an implement's or a resume's `{{PLAN}}`: where its copy of the approved plan is, and the plan's outline.

    The plan's text is never in the prompt: the worker reads the sections it needs from its copy (DESIGN §25). The
    outline is the plan's own headings, model-written, so it is fenced as data.

    Returns:
        `None.` without a copy; else the copy's path, then the headings in a fenced block, or a line saying it has none.
    """
    if copy is None:
        return "None."
    lines = [f"`{copy}` is the plan the operator approved for this ticket, a copy written for this run alone."]
    return "\n".join([*lines, *_outline(outline)])


def _outline(outline: Sequence[str]) -> list[str]:
    """Return a plan's outline for a prompt: its headings, model-written, fenced as data, or a line saying it has none.

    Returns:
        The lines.
    """
    if not outline:
        return ["It has no headings: read it whole."]
    fence = "````" if any("```" in heading for heading in outline) else "```"
    return ["Its outline, the plan's own headings:", "", f"{fence}text", *outline, fence]


def feedback_plan_note(copy: Path, outline: Sequence[str], items: Sequence[tuple[int, str, int, str]]) -> str:
    """Return a resume's `{{PLAN}}` when it follows a feedback plan (DESIGN §32): its copy, outline, and approved items.

    The items are the harness's, from the plan's validated result line, each its number, PR, observed id, and what the
    plan proposes: the operator approved the plan whole, so these are the items the run acts on, and the only ones.

    Returns:
        The copy's path and what it is, the outline as `plan_note` gives it, and a line per item.
    """
    what = (
        f"`{copy}` is the feedback plan the operator approved for this round of the PR's feedback, a copy written for "
        "this run alone. Their approval of it, whole, is their go-ahead for each item below, whoever wrote it, and for "
        "nothing else of the PR's feedback: leave any other review comment for the next plan."
    )
    lines = [what, *_outline(outline)]
    if items:
        lines += ["", "The items it covers, each by the review or comment id canopy observed on its PR:", ""]
        lines += [f"{n}. {pr}, item {item_id}: {proposal}" for n, pr, item_id, proposal in items]
        lines += [
            "",
            "For `change`, change the code as the plan says. For `decline`, `ask`, and `leave`, change nothing for it.",
        ]
    else:
        lines += ["", "It covers no review comment: work the reasons below as it says."]
    return "\n".join(lines)


def mark_comments(prefix: str, suffix: str, *, where: str = "on the ticket or a PR") -> str:
    """Return the instruction that has a worker mark each comment it posts (D069), `where` it posts them."""
    marks = [f"start it with `{prefix}` and a space"] if prefix else []
    if suffix:
        marks.append(f"end it with `{suffix}`")
    return f"In every comment and reply you post, {where}, {', and '.join(marks)}, without the backticks."


def commit_trailer(config: Config) -> str:
    """Return the trailer a worker adds to its commits when the agent runtime adds no attribution of its own."""
    return f"Co-authored-by: {config.trust.commit_trailer_name} <{config.trust.commit_trailer_email}>"


def commit_attribution(config: Config) -> str:
    """Return the instruction for a worker's commits: keep the runtime's trailer, or add canopy's while it is on."""
    if not config.trust.commit_trailer:
        return "Keep the agent runtime's attribution trailer on commits, if it adds one, and add no co-author trailer."
    return f"Keep the agent runtime's attribution trailer on commits, or add `{commit_trailer(config)}`."


def branch_update(config: Config, branch: str) -> str:
    """Return how a worker brings a base branch into `branch`: by merging, or with `trust.rebase`, by rebasing."""
    if not config.trust.rebase:
        return (
            "To bring a base branch into yours, merge `origin/<base>` into it. Never rebase or otherwise rewrite a "
            "commit that is already pushed: a push must never need force."
        )
    return (
        "To bring a base branch into yours, rebase onto `origin/<base>`, and never merge it in: the operator's "
        "repositories refuse merge commits. If this ticket was stacked on a PR that has since merged, rebase only this "
        "ticket's own commits, with `git rebase --onto origin/<base> <the last commit of the branch it was stacked "
        f"on>`. Push a rebased branch with `git push --force-with-lease origin HEAD:refs/heads/{branch}` in "
        "place of the plain push. That is the only force you may use, and a rebase the only reason to use it."
    )


def open_pr(skill: str) -> str:
    """Return how a worker opens a PR: through the GitHub MCP, or with the operator's skill and nothing else.

    A missing skill is a failed run, not a fallback to the MCP: the operator set the skill because the MCP's PRs do not
    work for them.
    """
    if not skill:
        return "Open each PR through the GitHub MCP."
    return (
        f"Open each PR by following the skill `{skill}`, and in no other way: load it before you open one. If no skill "
        f"named `{skill}` is available, open no PR and report `failed` with a summary that starts `no PR skill:`."
    )


def missing_notice(config: Config) -> list[tuple[Path, list[str]]]:
    """The operator's prompt overrides that lack `{{NOTICE}}`, with the kinds each refuses while a notice is in force.

    Returns:
        Each such override's path and the run kinds it serves (`review` for the reviewer's), in a fixed order.
    """
    found: list[tuple[Path, list[str]]] = []
    for name, kinds in _HEARS_NOTICE.items():
        override = config.paths.prompt_overrides / name
        if not override.is_file():
            continue
        try:
            used = set(_PLACEHOLDER_RE.findall(override.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            # A file that cannot be read fails every render already, with its own error.
            continue
        if "NOTICE" not in used:
            found.append((override, kinds))
    return found


def standing_instructions(config: Config) -> str:
    """Return the operator's standing instructions for `{{STANDING_INSTRUCTIONS}}`, or `None.` without any.

    A file that cannot be read, is not UTF-8, or is over `MAX_STANDING_BYTES` is an error, not an empty section: the
    operator set it for every worker, and a worker without it would work as if it had never been written.

    Raises:
        PromptError: The file cannot be read, is not UTF-8, or is over `MAX_STANDING_BYTES`.
    """
    return _standing(config.paths.worker_instructions, "worker")


def overseer_instructions(config: Config) -> str:
    """Return the operator's standing instructions to the overseer, or `None.` without any.

    They fail as the workers' do (`standing_instructions`): an overseer without them would decide as if they had never
    been written.

    Raises:
        PromptError: The file cannot be read, is not UTF-8, or is over `MAX_STANDING_BYTES`.
    """
    return _standing(config.paths.overseer_instructions, "overseer")


def reviewer_instructions(config: Config) -> str:
    """Return the operator's standing instructions to every reviewer, or `None.` without any.

    They fail as the workers' do (`standing_instructions`): a review without them would judge as if they had never
    been written.

    Raises:
        PromptError: The file cannot be read, is not UTF-8, or is over `MAX_STANDING_BYTES`.
    """
    return _standing(config.paths.reviewer_instructions, "reviewer")


def chore_instructions(config: Config) -> str:
    """Return the operator's standing instructions to every chore run, or `None.` without any.

    They fail as the workers' do (`standing_instructions`).

    Raises:
        PromptError: The file cannot be read, is not UTF-8, or is over `MAX_STANDING_BYTES`.
    """
    return _standing(config.paths.chore_instructions, "chore")


def standing_section(text: str, reader: Reader) -> str:
    """Return `{{STANDING_SECTION}}` for `reader`, from `text` as the functions above return it.

    Returns:
        The section, starting with the blank line before its heading, or the empty string when `text` is `None.`.
    """
    if text == "None.":
        return ""
    return f"\n\n{STANDING_HEADING}\n\n{text}\n\n{STANDING_FRAMING[reader]}"


def render_overseer(config: Config) -> str:
    """Return the overseer's prompt with its standing instructions in place of `REQUIRED_STANDING`'s placeholders.

    Nothing else in it is replaced: an override may hold `{{` text of its own. With `paths.overseer_instructions` set,
    a prompt without either placeholder is an error, not a prompt that drops them.

    Raises:
        PromptError: The prompt or the instructions cannot be read, or the prompt lacks the placeholder they need.
    """
    path = prompt_path(config, OVERSEER)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise PromptError(f"cannot read the overseer prompt {path}: {e}") from e
    section, plain = (f"{{{{{n}}}}}" for n in REQUIRED_STANDING)
    if config.paths.overseer_instructions is not None and section not in text and plain not in text:
        raise PromptError(f"{path}: missing required placeholder {section} or {plain}")
    standing = overseer_instructions(config)
    return text.replace(section, standing_section(standing, "overseer")).replace(plain, standing)


def persona() -> str:
    """Return the text of `DEFAULT_PERSONA`, from the personas canopy ships, for `{{PERSONA}}` (DESIGN §31).

    Raises:
        PromptError: The file cannot be read or is not UTF-8.
    """
    try:
        path = resources.personas_dir() / f"{DEFAULT_PERSONA}.md"
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as e:
        raise PromptError(f"cannot read persona {DEFAULT_PERSONA}: {e}") from e


class PromptError(Exception):
    """A prompt file cannot be rendered."""


def prompt_path(config: Config, name: str) -> Path:
    """Return the prompt file `name`, preferring the operator's override."""
    override = config.paths.prompt_overrides / name
    if override.is_file():
        return override
    return resources.prompts_dir() / name


def render_worker(
    config: Config,
    kind: str,
    values: Mapping[str, str],
    *,
    required: Sequence[str] = (),
    private: bool = False,
    notice: str | None = None,
) -> str:
    """Return the worker prompt for `kind` with every `{{NAME}}` replaced from `values`.

    Replacement is one pass, so a value that itself contains `{{NAME}}` is left as it is. A placeholder with no value
    is an error: an override with a typo must not reach a worker half rendered. So is a prompt that lacks one of
    `REQUIRED_WORKER` (`REQUIRED_PLAN` for a plan's), or of `required`, and, with `runtime.pr_skill` set, a prompt for
    a kind that opens PRs that lacks `REQUIRED_PR_SKILL`. A `private` prompt is a private ticket's, which must carry
    `REQUIRED_PRIVATE` in place of `REQUIRED_WORKER`: it checks no label. A plan has one prompt for both, which carries
    its own check. `{{STANDING_SECTION}}` comes from the config, not `values`, and with `paths.worker_instructions`
    set every prompt must carry it, or `{{STANDING_INSTRUCTIONS}}`, the text alone. `{{PERSONA}}` is
    `DEFAULT_PERSONA`'s text, which a prompt need not carry. `{{COMMIT_ATTRIBUTION}}` and `{{COMMIT_TRAILER}}` come
    from the config too: with `trust.commit_trailer_name` or `trust.commit_trailer_email`
    changed from the default every prompt for a kind that commits must carry one of them, and with
    `trust.commit_trailer` off it must carry `{{COMMIT_ATTRIBUTION}}`. So does `{{BRANCH_UPDATE}}`, which every such
    prompt must carry with `trust.rebase` set. `notice` is the operator's notice in force (`core.notice`), for
    `{{NOTICE}}`: with one, every prompt must carry it.
    """
    values = {
        # Agent memory's parts (DESIGN §28): empty unless dispatch rendered them, so with memory off every prompt is
        # the same bytes as before it existed.
        **dict.fromkeys(MEMORY_PARTS, ""),
        **values,
        **_standing_values(standing_instructions(config), _worker_reader(kind, private=private)),
        "PERSONA": persona(),
        "NOTICE": notice if notice is not None else "None.",
        "COMMIT_ATTRIBUTION": commit_attribution(config),
        "COMMIT_TRAILER": commit_trailer(config),
        "BRANCH_UPDATE": branch_update(config, values.get("BRANCH", "")),
    }
    pr_skill = REQUIRED_PR_SKILL if config.runtime.pr_skill and kind in OPENS_PRS else ()
    rebase = REQUIRED_REBASE if config.trust.rebase and kind in COMMITS else ()
    noticed = REQUIRED_NOTICE if notice is not None else ()
    required = (*pr_skill, *rebase, *noticed, *required)
    standing = (REQUIRED_STANDING,) if config.paths.worker_instructions is not None else ()
    one_of = (*standing, *((_required_attribution(config),) if kind in COMMITS else ()))
    if kind == RunKind.PLAN:
        return render(config, WORKER[kind], values, required=(*REQUIRED_PLAN, *required), one_of=one_of)
    if kind == RunKind.FEEDBACK_PLAN:
        return render(config, FEEDBACK_PLAN, values, required=(*REQUIRED_FEEDBACK_PLAN, *required), one_of=one_of)
    if private:
        return render(config, WORKER_PRIVATE[kind], values, required=(*REQUIRED_PRIVATE, *required), one_of=one_of)
    return render(config, WORKER[kind], values, required=(*REQUIRED_WORKER, *required), one_of=one_of)


def render_reviewer(
    config: Config, values: Mapping[str, str], *, notice: str | None = None, notes: str | None = None
) -> str:
    """Return the reviewer's prompt (DESIGN §21) with every `{{NAME}}` replaced from `values`.

    It must carry `REQUIRED_REVIEWER`. `notice` is the operator's notice in force (`core.notice`), for `{{NOTICE}}`:
    a review reads CI too, so with one the prompt must carry it. `notes` are the operator's on the review request the
    review answers, for `{{NOTES}}`, which the prompt must carry when there are some. `{{PERSONA}}` is
    `DEFAULT_PERSONA`'s text, as a worker's is. `{{STANDING_SECTION}}` comes from the config, and with
    `paths.reviewer_instructions` set the prompt must carry it, or `{{STANDING_INSTRUCTIONS}}`, the text alone.

    Returns:
        The rendered prompt.
    """
    values = {
        **values,
        **_standing_values(reviewer_instructions(config), "reviewer"),
        "NOTICE": notice if notice is not None else "None.",
        "NOTES": notes or "None.",
        "PERSONA": persona(),
    }
    standing = (REQUIRED_STANDING,) if config.paths.reviewer_instructions is not None else ()
    noticed = REQUIRED_NOTICE if notice is not None else ()
    noted = REQUIRED_NOTES if notes else ()
    return render(config, REVIEWER, values, required=(*REQUIRED_REVIEWER, *noticed, *noted), one_of=standing)


def render(
    config: Config,
    name: str,
    values: Mapping[str, str],
    *,
    required: Sequence[str] = (),
    one_of: Sequence[Sequence[str]] = (),
) -> str:
    """Return prompt file `name` with every `{{NAME}}` replaced from `values`, in one pass.

    A placeholder with no value is an error, and so is a prompt that lacks one of `required`, or every one of a group
    in `one_of`.

    Raises:
        PromptError: The prompt has a placeholder `values` has no value for, lacks one of `required`, or lacks every
            one of a group in `one_of`.
    """
    path = prompt_path(config, name)
    text = path.read_text(encoding="utf-8")

    def replace(m: re.Match[str]) -> str:
        placeholder = m.group(1)
        if placeholder not in values:
            raise PromptError(f"{path}: unknown placeholder {{{{{placeholder}}}}}")
        return values[placeholder]

    rendered = _PLACEHOLDER_RE.sub(replace, text)
    used = set(_PLACEHOLDER_RE.findall(text))
    missing = [f"{{{{{n}}}}}" for n in required if n not in used]
    missing.extend(" or ".join(f"{{{{{n}}}}}" for n in group) for group in one_of if group and used.isdisjoint(group))
    if missing:
        raise PromptError(f"{path}: missing required placeholder {', '.join(missing)}")
    return rendered


def _worker_reader(kind: str, *, private: bool) -> Reader:
    # How a worker prompt for `kind` frames the standing instructions: as a plan's, a private ticket's, or a worker's.
    if kind in {RunKind.PLAN, RunKind.FEEDBACK_PLAN}:
        return "planner"
    return "private" if private else "worker"


def _standing_values(text: str, reader: Reader) -> dict[str, str]:
    # Both standing placeholders' values from the instructions' `text`: the section the shipped prompts carry, and the
    # text alone for an override written before it.
    return {STANDING_SECTION: standing_section(text, reader), STANDING_TEXT: text}


def _standing(path: Path | None, reader: str) -> str:
    # The text of a standing-instructions file for `reader`'s prompts, or `None.` when none is set or it is blank.
    if path is None:
        return "None."
    try:
        data = path.read_bytes()
        text = data.decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise PromptError(f"cannot read {reader} instructions {path}: {e}") from e
    if len(data) > MAX_STANDING_BYTES:
        raise PromptError(f"{reader} instructions {path} are {len(data)} bytes, over {MAX_STANDING_BYTES}")
    return text.strip() or "None."


def _required_attribution(config: Config) -> tuple[str, ...]:
    # What a committing kind's prompt must carry, one of, for its commits to be attributed as configured.
    if not config.trust.commit_trailer:
        return REQUIRED_NO_TRAILER
    custom = (config.trust.commit_trailer_name, config.trust.commit_trailer_email) != (
        DEFAULT_TRAILER_NAME,
        DEFAULT_TRAILER_EMAIL,
    )
    return REQUIRED_TRAILER if custom else ()
