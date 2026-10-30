// What each attention reason and each phase means, in a line: a word's tip says it under the CLI's spelling, so an
// operator who meets `review_late` learns what it is without opening the guide. The reasons are DESIGN §14's, the
// phases the phase table's (§7); the operator skill's table of reasons says what to do about each.

/** What each reason canopy raises an attention item for means. The overseer may record others, which have none. */
export const REASON_MEANINGS: Readonly<Record<string, string>> = {
    needs_reviewer: 'The PR is green and unreviewed: review it.',
    ready_to_merge: 'The PR is approved: merge it. canopy never merges.',
    needs_author: 'A review comment needs a person (design pushback, scope), or a stacked-on PR closed: decide.',
    untrusted_review: 'Feedback from a reviewer not in trust.trusted_reviewers: say what to do with it in a reply.',
    untrusted_artifact_comment: 'An author you do not list commented on the ticket’s artifacts: reply to send it on.',
    awaiting_reply: 'A worker, a planner, or a task asked a question and waits on your answer.',
    plan_review: 'A plan waits on you: approve it, or reply with what to change.',
    run_question: 'A running worker, planner, or reviewer asks you a question it works around: answer by letter.',
    plan_changed: 'An approved plan’s file changed: approve it again, plan anew, or skip the plan.',
    drafts_waiting: 'A run drafted replies for you: edit, drop, or send each.',
    review_waiting: 'A review you asked for is done: read its draft, then publish or discard it.',
    review_unsettled: 'A review you staged waits for you to submit or delete it on GitHub, or its publish is unknown.',
    review_rebuttal: 'A review rebutted a worker’s decline of its finding: send the finding on, or dismiss it.',
    review_late: 'A review found something in code unchanged since the PR’s first review: send it on, or dismiss it.',
    attempt_limit: 'The ticket, one of its PRs, or its plan used up its runs of one kind: take it over, or grant more.',
    crashed: 'The ticket’s latest run crashed: read its log. A reply or a message tries again.',
    unpushed: 'The ticket’s latest run ended with work it did not push: read its log.',
    unknown_result: 'The ticket’s latest run ended without a result canopy could read, or timed out: read its log.',
    worker_failed: 'The ticket’s latest run failed: read its log. A reply or a message tries again.',
    chore_failed: 'A chore’s latest run could not check (failed, timed out, crashed): read its log.',
    review_failed: 'The PR’s latest review run failed: read what it said.',
    review_limit: 'The PR reached its limit of reviews: grant it another, or review it yourself.',
    notice_rerun: 'A check failed during an outage your notice named, and the notice has ended: rerun the check.',
    flaky_rerun: 'A worker judged a failed check flaky and changed nothing for it: rerun it, or reply that it is real.',
    fix_ci_override:
        'You override the retired fix-ci prompt, so every resume is refused until you remove the override.',
    repo_missing: 'A repository in the workspace map has no clone: sync the workspace.',
    auto_maintenance_on: 'A clone leaves git’s automatic maintenance on: sync the workspace to turn it off.',
    multi_repo: 'Independent pieces in several repositories: decide, or ask for a split.',
    follow_up_unrecorded: 'The ticket’s runs reported follow-up tickets the journal did not record.',
    archive_unpushed: 'The plan archive is not all pushed to its upstream: the detail says why.',
    memory_proposal: 'A done ticket’s runs proposed lessons: promote or reject each.',
    lesson_review: 'Lessons are due for review: renew, graduate, or forget each.',
    lesson_wrong: 'A run reported a lesson wrong: renew or forget it.',
    connector_failed: 'A source read less than it was asked this tick, so what it observes may be stale.',
    unobserved_pr: 'A unit’s PR URL names no PR, so no source reads it and the ticket waits: forget its work.',
    persona_missing: 'A run or a review was refused: the persona it names has no file.',
    bad_persona: 'A run or a review was refused: its persona’s file is one canopy will not put in a prompt.',
    model_missing: 'The runtime does not list the model chosen, so nothing runs on it: choose another, or fix it.',
    model_list_failed: 'The runtime’s list of models could not be read, so nothing runs: fix the runtime.',
    git_too_old: 'The git on PATH is too old for canopy’s commit hooks: upgrade it.',
    task_ticket_unrecorded: 'A task’s run named a ticket canopy did not record: reply to the task, or start it.',
    canopy_unavailable:
        'The server of the overseer’s tools did not answer, so the overseer did not run: fix the install.',
    disk_low: 'The workspace or .canopy/ is short of free disk, so the overseer did not run: free space.',
}

/** What each phase of a ticket or a PR means: where it stands, as the overseer last worked it out. */
export const PHASE_MEANINGS: Readonly<Record<string, string>> = {
    ready: 'Labeled for canopy, with no run, no branch, and no open blocker: the next to start.',
    plan_proposed: 'Its newest plan waits on you to approve it or reply.',
    blocked: 'Ready, but a ticket it depends on is still open.',
    running: 'A run is on it now: a worker’s, or a planner’s.',
    pushed_no_pr: 'Its branch is pushed, with no PR yet.',
    conflicted: 'Its PR conflicts with its base branch.',
    ci_running: 'Its PR’s checks are still running.',
    ci_red: 'Its PR’s checks failed.',
    review_pending: 'Its PR’s checks pass and canopy has not reviewed its head commit yet.',
    review_findings: 'canopy’s review of its PR’s head found something to fix.',
    changes_requested: 'A trusted reviewer commented on its PR, or requested changes.',
    untrusted_review: 'A reviewer not in trust.trusted_reviewers commented on its PR: it waits on your word.',
    green_unreviewed: 'Its PR’s checks pass, with no approval yet: it needs a reviewer.',
    approved: 'Its PR is approved and not merged: it waits on a person to merge it.',
    merged: 'Its PR is merged.',
    needs_human: 'A run, a worker’s or a planner’s, asked a question, and no authorized reply has come since.',
    human_replied: 'An authorized reply, or your message, came since its question: a worker resumes with it.',
    split: 'Split into follow-up tickets, which canopy no longer does.',
}

/** What an attention reason means, or null for one canopy does not know, such as one the overseer made up. */
export function reasonMeaning(reason: string): string | null {
    return Object.hasOwn(REASON_MEANINGS, reason) ? (REASON_MEANINGS[reason] ?? null) : null
}

/** What a ticket's or a PR's phase means, or null for none. */
export function phaseMeaning(phase: string | null): string | null {
    return phase !== null && Object.hasOwn(PHASE_MEANINGS, phase) ? (PHASE_MEANINGS[phase] ?? null) : null
}
