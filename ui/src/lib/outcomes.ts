import type {
    ConfigReload,
    Dismissed,
    Forgot,
    Granted,
    NoticeChanged,
    PlanChanged,
    Replied,
    ReviewDismissed,
    ReviewRequested,
    ReviewRequestStopped,
    ReviewSent,
    Started,
    Stopped,
} from '@/api/types'

// What each of the operator's actions did, in the words the CLI's verb prints (canopy/cli/conversation.py).

/** What a start did, as `canopy start` says it: whether it was already started, and any run still working it. */
export function startedText(key: string, started: Started): string {
    const state = started.already ? 'was already started' : 'is started'
    const head = `${key} ${state}, privately: workers read it and write nothing to it.`
    if (started.running_run === null) {
        return `${head} The next tick picks it up.`
    }
    const kind = started.running_private
        ? 'private'
        : 'public, dispatched before this start, so it may write to the ticket'
    return `${head} Run ${started.running_run} (${kind}) is still working it.`
}

/** What a stop did, as `canopy stop` says it: whether it was already stopped, and with `now`, whether its run ended. */
export function stoppedText(key: string, stopped: Stopped, now: boolean): string {
    const head = `${key} ${stopped.already ? 'was already stopped' : 'is stopped'}; nothing dispatches it now.`
    if (stopped.running_run === null) {
        return head
    }
    if (!now) {
        return `${head} Run ${stopped.running_run} is still working it and will finish.`
    }
    return stopped.ended
        ? `${head} Run ${stopped.running_run} was ended and its slots returned.`
        : `${head} Run ${stopped.running_run} had already ended.`
}

/** What a forget cleared, and what is left for the operator: closing its PRs and deleting its branch on origin. */
export function forgotText(key: string, forgot: Forgot): string {
    const head = `${key} is forgotten: its next implement starts over on a new branch.`
    const named = [...(forgot.branch === null ? [] : [`branch ${forgot.branch}`]), ...forgot.prs]
    if (named.length === 0) {
        return head
    }
    return (
        `${head} canopy no longer tracks ${named.join(', ')}. ` +
        'Close its PRs and delete its branch on origin yourself: until you do, the overseer still finds them and the ' +
        'ticket cannot start over.'
    )
}

/**
 * What a grant did, as `canopy grant` says it: the runs so far, which still count, and the limit now. `subject` is the
 * ticket's key, or the PR's URL for its reviews.
 */
export function grantedText(subject: string, granted: Granted): string {
    if (granted.kind === 'review') {
        return (
            `${subject} has had ${granted.runs} review runs, and may now have ${granted.limit}. ` +
            'The next tick decides whether to review it.'
        )
    }
    return (
        `${subject} in ${granted.repo ?? 'its repository'} has had ${granted.runs} ${granted.kind} runs, and may now ` +
        `have ${granted.limit}. The next tick decides whether to dispatch it.`
    )
}

/** What a note to a chore did, as `canopy reply chore:NAME` says it: its next runs read it, not the next tick. */
export function notedText(name: string, replied: Replied): string {
    if (replied.new) {
        return `Recorded message ${replied.message_id} on chore:${name}. Its next run reads it.`
    }
    return `Message ${replied.message_id} on chore:${name} already says this; nothing new recorded.`
}

/** What a dismissal did, as `canopy dismiss` says it: off the attention list until it clears, or listed again. */
export function dismissedText(dismissed: Dismissed): string {
    const head = `chore:${dismissed.chore} ${dismissed.finding}`
    if (dismissed.dismissed) {
        return `${head} is dismissed: it is off the attention list until the chore stops reporting it.`
    }
    return `${head} is listed again while the chore reports it.`
}

/** What a dismissal of a review's finding did, as `canopy dismiss review:ID N` says it. */
export function reviewDismissedText(dismissed: ReviewDismissed): string {
    const head = `review:${dismissed.run} finding ${dismissed.finding}`
    if (dismissed.dismissed) {
        return `${head} is dismissed: no worker or tick acts on it.`
    }
    return `${head} is no longer dismissed: a resume hands it to the worker again.`
}

/** What sending a review's findings did, as `canopy send review:ID N...` says it. */
export function reviewSentText(sent: ReviewSent): string {
    const head = `review:${sent.run} findings ${sent.findings.join(', ')}`
    const to = `${sent.ticket_key} as message ${sent.message_id}`
    if (sent.new) {
        return `${head} went to ${to}: the next tick reads it as your go-ahead.`
    }
    return `${head} already went to ${to}.`
}

/** What a reply did, as `canopy reply` says it: the message it recorded, or the one that already said it. */
export function repliedText(key: string, replied: Replied): string {
    const answered = replied.answers === null ? '' : `, answering message ${replied.answers}`
    if (replied.new) {
        return `Recorded message ${replied.message_id} on ${key}${answered}. The next tick reads it.`
    }
    return `Message ${replied.message_id} on ${key} already says this${answered}; nothing new recorded.`
}

/** What setting a notice did, as `canopy notice` says it: the runs that hear it. The banner says until when. */
export function noticeSetText(changed: NoticeChanged): string {
    if (changed.loop.notice === null) {
        return 'The notice lapsed already: runs dispatched from now on hear none.'
    }
    return 'Notice set: runs dispatched from now on hear it until it lapses. The loop ticks soon.'
}

/** What a reload found, as the loop's terminal says it: the keys that changed, when the loop runs on them, and which
 * wait for a restart. With nothing changed there is nothing to apply, so it says only that. */
export function reloadedText(reload: ConfigReload): string {
    if (reload.changed.length === 0) {
        return 'Nothing changed: the config files say what the loop already runs on.'
    }
    const what = `${reload.changed.join(', ')} changed`
    const when = reload.after_tick
        ? 'The loop runs on the new config once the running tick ends.'
        : 'The loop runs on the new config now.'
    const count = reload.restart.length
    const restart =
        count === 0 ? '' : ` ${reload.restart.join(', ')} take${count === 1 ? 's' : ''} effect on a restart.`
    return `${what}. ${when}${restart}`
}

/** What a review request did, as `canopy start URL --review` says it: new, or already open. */
export function reviewRequestedText(url: string, requested: ReviewRequested): string {
    if (requested.already) {
        return `${url} was already requested for review.`
    }
    return `${url} is requested for review. The next tick reviews its head, once.`
}

/** What stopping a review request did, as `canopy stop URL` says it, and a review of the PR still running. */
export function reviewStoppedText(url: string, stopped: ReviewRequestStopped): string {
    const head = `${url}'s review request is stopped; nothing reviews it now.`
    if (stopped.running_review === null) {
        return head
    }
    return `${head} Review run ${stopped.running_review} of it is still running and will finish.`
}

/** What the operator's word on a plan did, as `canopy plan` says it (canopy/cli/plans.py). */
export function planText(key: string, changed: PlanChanged): string {
    const superseded =
        changed.superseded === null ? '' : `Plan ${changed.superseded} of ${key} is superseded; its file stays. `
    if (changed.action === 'approve') {
        return `Plan ${changed.plan} of ${key} is approved as its file stands now. The next tick can implement it.`
    }
    if (changed.action === 'skip') {
        const state = changed.already ? 'was already skipped' : 'is skipped'
        return `${superseded}${key}'s plan ${state}: its implement goes ahead without one.`
    }
    if (changed.already) {
        return `${key} already waits on a plan: the next tick dispatches a planner if none is running.`
    }
    return (
        `${superseded}${key} is planned first: the next tick dispatches a planner, and nothing is implemented until ` +
        'you approve its plan.'
    )
}
