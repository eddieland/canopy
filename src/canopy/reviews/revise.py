"""`canopy review revise`: a revision of a review's draft on the operator's notes (DESIGN §34).

A revision is a review run at the commit the review read, of a PR the loop does not own, which reads the PR and the
draft, writes nothing anywhere, and reports a new version. Only a note of the operator's newer than the draft's newest
version asks for one, and only a tick starts one (D020). It is held by §21's guards but two, a `done` review of its
commit (its review is one) and the PR's limit: `max_reviews` above 0, its repository cloned, nothing else reviewing or
revising the PR, and the daily limit, review capacity, and `max_workers` with room. In their place, its draft's
own limit, `policy.max_revisions_per_draft` plus the operator's grants, never reset (D030). A refusal is raised as
`start.Refusal`; the CLI records it as `refused:<guard>`.

It runs as the reviewer does, `canopy _review` with `canopy-reviewer`, in a leased slot and outside the checkout. Its
prompt carries the review, the newest version, and the notes since it: the notes are its only instructions, and the PR
and the draft are data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from canopy.core import db, personas, prompts, recorded_runs, review_drafts, review_revisions, review_runs
from canopy.core import review_result as result
from canopy.core.conversation import printable
from canopy.core.vocab import RecordedKind, ReviewDraftStatus
from canopy.infra import lock
from canopy.reviews import findings, start

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from canopy.core import records
    from canopy.core.context import Context


@dataclass(frozen=True)
class Target:
    """What a revision revises: the review, its draft's newest version, the notes since it, and where it leases."""

    review: records.ReviewRun
    draft: records.ReviewDraft
    version: review_drafts.Version
    notes: Sequence[records.ReviewDraftNote]
    repo: str
    #: This revision's number, from 1, and how many the draft may have.
    attempt: int
    limit: int


def check(ctx: Context, *, tick_id: int, run_id: int) -> Target:
    """Check the guards for a dry run, counting what this dry run already started as running (D036).

    Returns:
        What the revision would revise.

    Raises:
        start.Refusal: a guard refused.
    """
    planned = db.decisions_for_tick(ctx.conn, tick_id)
    with lock.hold(ctx.dispatch_lock_path, wait=True):
        target = _guard(ctx, run_id, planned=planned)
        _persona(ctx, target.review)
        return target


def record(ctx: Context, *, tick_id: int, run_id: int, rank: int, asked: str) -> tuple[Target, int]:
    """Check the guards a revision the overseer asks for passes, and record it for its tick to start (DESIGN §8).

    Nothing is leased or spawned: the tick starts it, by `begin`, once the overseer's run ends, under every guard again.
    Until then it counts as running: a review or revision of its PR is refused `running`, and it counts toward the
    day's reviews, `max_reviews`, and `max_workers`. `asked` is the overseer's request as JSON, which the tick starts it
    from, and `rank` its place in §7's order.

    Returns:
        What the revision revises, and the recorded run's id.

    Raises:
        start.Refusal: a guard refused.
    """
    with lock.hold(ctx.dispatch_lock_path, wait=True):
        target = _guard(ctx, run_id, held=recorded_runs.held(ctx.conn))
        _persona(ctx, target.review)
        recorded = recorded_runs.record(
            ctx.conn,
            tick_id=tick_id,
            kind=RecordedKind.REVISION,
            rank=rank,
            request=asked,
            pr=target.review.pr_url,
        )
        return target, recorded


def begin(ctx: Context, *, tick_id: int, run_id: int, recorded: int | None = None) -> start.Started:
    """Check the guards, record the revision as a review run, lease a slot, render its prompt, and spawn `_review`.

    `recorded` is the run the overseer asked for that this starts (`record`): every other run recorded and not yet
    started counts as running.

    Returns:
        The new revision's run id, the pid of its `canopy _review`, and the slot it leased.

    Raises:
        start.Refusal: a guard refused, or the slot could not be leased, the prompt rendered, or the run started.
            Nothing is left running and no slot is left leased.
    """
    with lock.hold(ctx.dispatch_lock_path, wait=True):
        target = _guard(ctx, run_id, held=recorded_runs.held(ctx.conn, but=recorded))
        persona = _persona(ctx, target.review)
        review = target.review
        revision = review_runs.insert_review_run(
            ctx.conn,
            tick_id=tick_id,
            pr_url=review.pr_url,
            sha=review.sha,
            ticket=None,
            repo=target.repo,
            purpose=review.purpose,
            logs_dir=start.reviews_dir(ctx),
            persona=persona.name,
            persona_digest=persona.digest,
            revises=(target.draft.id, target.version.number),
        )
        # The diff the draft sits on is the review's, from the base it read.
        lease = start.lease_slot(ctx, revision, target.repo, base=review.base_branch)
        with start.returned_on_failure(ctx, target.repo, lease):
            prompt = _prompt(ctx, revision, target, persona)
            return start.spawn(ctx, revision, lease, prompt)


def _guard(
    ctx: Context,
    run_id: int,
    *,
    planned: Collection[records.Decision] | None = None,
    held: Sequence[records.RecordedRun] = (),
) -> Target:
    """Refuse unless a revision of review run `run_id`'s draft may start now.

    `planned` is a dry run's decisions this tick: its reviews, revisions, and worker dispatches count as running, as
    the runs in `held` do, recorded and not yet started (DESIGN §8).

    Returns:
        What the revision revises.

    Raises:
        start.Refusal: reviews are off; the run or its draft is not one to revise (`unknown`, `no_draft`, `not_ours`,
            `not_waiting`, `no_diff`); no note asks for a revision (`no_note`); the repository is not cloned; a review
            or revision of the PR runs (`running`); the draft has had its revisions (`revision_limit`); or there is no
            room (`check_room`'s).
    """
    # The operator's note authorizes a revision, as a request does a review, so `review.query` need not be set.
    if ctx.config.capacity.max_reviews <= 0:
        raise start.Refusal("reviews_off", "reviews are off: capacity.max_reviews is 0")
    review, draft = _draft(ctx, run_id)
    version = review_drafts.newest(ctx.conn, draft.id)
    notes = review_revisions.pending(ctx.conn, draft.id)
    if not notes:
        raise start.Refusal(
            "no_note",
            f"no note of the operator's on review run {run_id}'s draft is newer than its version {version.number}; "
            "nothing asks for a revision",
        )
    repo = start.check_repo(ctx, review.repo)
    planned_reviews, planned_runs = start.split_planned(planned or [])
    _check_running(ctx, review, planned_reviews, held)
    spent = len(review_runs.revision_runs_of(ctx.conn, draft.id))
    most = review_revisions.limit(ctx.conn, ctx.config, draft.id)
    if spent >= most:
        raise start.Refusal(
            "revision_limit",
            f"review run {run_id}'s draft has had {spent} revisions and its limit is {most}",
        )
    start.check_room(ctx, planned_reviews, planned_runs, held=held)
    return Target(review, draft, version, notes, repo, attempt=spent + 1, limit=most)


def _draft(ctx: Context, run_id: int) -> tuple[records.ReviewRun, records.ReviewDraft]:
    """The review run `run_id` names, and its draft, if it is one a revision may revise.

    Returns:
        The review and its draft.

    Raises:
        start.Refusal: (`unknown`) no such review, or it is itself a revision; (`no_draft`) it has no draft;
            (`not_ours`) a ticket's unit holds its PR now; (`not_waiting`) its draft is published, staged, or being
            posted; (`no_diff`) the diff its draft's comments sit on is gone.
    """
    review = review_runs.get_review_run(ctx.conn, run_id)
    if review is None or review.revises is not None:
        raise start.Refusal(
            "unknown",
            f"there is no review run {run_id} with a draft to revise; --run names the review",
        )
    draft = review_drafts.of_review(ctx.conn, run_id)
    if draft is None:
        raise start.Refusal(
            "no_draft",
            f"review run {run_id} has no draft: only a review of a PR the loop does not own",
        )
    if not review_drafts.draftable(ctx.conn, review):
        raise start.Refusal("not_ours", f"{review.pr_url} is one of the loop's own PRs now: its draft is not revised")
    if draft.status is not ReviewDraftStatus.WAITING:
        raise start.Refusal("not_waiting", f"review run {run_id}'s draft is {draft.status}: it takes no revision")
    if review_drafts.diff_of(review) is None:
        raise start.Refusal("no_diff", f"the diff review run {run_id} read is gone, so its draft is not revised")
    return review, draft


def _check_running(
    ctx: Context,
    review: records.ReviewRun,
    planned_reviews: Collection[records.Decision],
    held: Sequence[records.RecordedRun],
) -> None:
    """`running`: a review or a revision of the PR is running or recorded to start, or this dry run already started one.

    A revision of a draft must not race another of it, and one review run of a PR at a time keeps a revision from
    reading the PR while a review of a newer commit is under way.

    Raises:
        start.Refusal: (`running`) one is.
    """
    busy = next((r for r in db.running_runs(ctx.conn, "review_runs") if r["pr_url"] == review.pr_url), None)
    if busy is not None:
        raise start.Refusal("running", f"review run {busy['id']} of this PR is running")
    if any(d.pr == review.pr_url for d in planned_reviews):
        raise start.Refusal("running", "this dry run already reviewed or revised this PR")
    recorded = next((r for r in recorded_runs.reviews(held) if r.pr == review.pr_url), None)
    if recorded is not None:
        raise start.Refusal("running", f"recorded run {recorded.id} of this PR starts once the overseer's run ends")


def _persona(ctx: Context, review: records.ReviewRun) -> personas.Persona:
    """The persona the review was written in, read now, so the revision keeps its voice; the reviewer's for an old one.

    Returns:
        The persona.

    Raises:
        start.Refusal: `persona_missing` or `bad_persona`, with its attention item, as a review's start refuses.
    """
    try:
        if review.persona is not None:
            return personas.load(ctx.config, review.persona)
        return personas.for_run(ctx.conn, ctx.config, "reviewer", None)
    except personas.PersonaError as e:
        raise start.Refusal(e.guard, e.reason, attention=e.guard) from e


def _prompt(ctx: Context, run_id: int, target: Target, persona: personas.Persona) -> str:
    """Render the reviser's prompt for revision `run_id`.

    Returns:
        The prompt.

    Raises:
        start.Refusal: (`bad_prompt`) it does not render; the run, which never started, is forgotten.
    """
    cfg = ctx.config
    review = target.review
    values = {
        "PR_URL": review.pr_url,
        "SHA": review.sha,
        "CHECKOUT": str(start.run_dir(ctx, run_id) / start.CHECKOUT_LINK),
        "REVIEW_RUN": str(review.id),
        "ATTEMPT": str(target.attempt),
        "MAX_ATTEMPTS": str(target.limit),
        "REVIEW": findings.for_reviser(ctx.conn, review),
        "DRAFT": _draft_text(target.version),
        "NOTES": _notes_text(target.notes),
        "TIMEOUT_MINUTES": str(cfg.runtime.review_timeout_minutes),
        "CONTRACT": result.REVISION_CONTRACT,
    }
    try:
        return prompts.render_reviser(cfg, values, persona=persona)
    except (OSError, prompts.PromptError) as e:
        # Nothing started, so it costs the draft none of its revisions; the caller returns the slot.
        review_runs.delete_review_run(ctx.conn, run_id)
        raise start.Refusal("bad_prompt", str(e)) from e


def _draft_text(version: review_drafts.Version) -> str:
    """Return `{{DRAFT}}`: a version of a review's draft as the reviser reads it, every text quoted, as data.

    Returns:
        Its body, and each comment under its `path:line`.
    """
    lines = [f"Version {version.number}."]
    lines += ["", "The body:", _quoted(version.body)] if version.body else ["", "The body: none."]
    for n, comment in enumerate(version.comments, 1):
        lines += ["", f"Comment {n}, on `{printable(comment.path)}:{comment.line}`:", _quoted(comment.text)]
    if not version.comments:
        lines += ["", "Comments: none."]
    return "\n".join(lines)


def _notes_text(notes: Sequence[records.ReviewDraftNote]) -> str:
    """Return `{{NOTES}}`: the operator's notes since the version, oldest first, each quoted.

    Returns:
        The notes.
    """
    return "\n\n".join(f"Note {n.id}:\n{_quoted(n.body)}" for n in notes)


def _quoted(text: str) -> str:
    # A text as a quote, one `> ` line per line, without control characters.
    return "\n".join(f"> {line}" for line in printable(text).splitlines() or [""])
