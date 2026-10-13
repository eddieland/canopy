import type { ConfigReload, Forgot, Replied, Started, Stopped } from '@/api/types'

// What each of the operator's actions did, in the words the CLI's verb prints (canopy/cli/conversation.py).

/** What a start did, as `canopy start` says it: whether it was already started, and any run still working it. */
export function startedText(key: string, started: Started): string {
    const state = started.already ? 'was already started' : 'is started'
    const head = `${key} ${state}, privately: workers read it and write nothing to it.`
    if (started.running_run === null) return `${head} The next tick picks it up.`
    const kind = started.running_private
        ? 'private'
        : 'public, dispatched before this start, so it may write to the ticket'
    return `${head} Run ${started.running_run} (${kind}) is still working it.`
}

/** What a stop did, as `canopy stop` says it: whether it was already stopped, and with `now`, whether its run ended. */
export function stoppedText(key: string, stopped: Stopped, now: boolean): string {
    const head = `${key} ${stopped.already ? 'was already stopped' : 'is stopped'}; nothing dispatches it now.`
    if (stopped.running_run === null) return head
    if (!now) return `${head} Run ${stopped.running_run} is still working it and will finish.`
    return stopped.ended
        ? `${head} Run ${stopped.running_run} was ended and its slots returned.`
        : `${head} Run ${stopped.running_run} had already ended.`
}

/** What a forget cleared, and what is left for the operator: closing its PRs and deleting its branch on origin. */
export function forgotText(key: string, forgot: Forgot): string {
    const head = `${key} is forgotten: its next implement starts over on a new branch.`
    const named = [...(forgot.branch === null ? [] : [`branch ${forgot.branch}`]), ...forgot.prs]
    if (named.length === 0) return head
    return (
        `${head} canopy no longer tracks ${named.join(', ')}. ` +
        'Close its PRs and delete its branch on origin yourself: until you do, the overseer still finds them and the ' +
        'ticket cannot start over.'
    )
}

/** What a note to a chore did, as `canopy reply chore:NAME` says it: its next runs read it, not the next tick. */
export function notedText(name: string, replied: Replied): string {
    if (replied.new) return `Recorded message ${replied.message_id} on chore:${name}. Its next run reads it.`
    return `Message ${replied.message_id} on chore:${name} already says this; nothing new recorded.`
}

/** What a reply did, as `canopy reply` says it: the message it recorded, or the one that already said it. */
export function repliedText(key: string, replied: Replied): string {
    const answered = replied.answers !== null ? `, answering message ${replied.answers}` : ''
    if (replied.new) return `Recorded message ${replied.message_id} on ${key}${answered}. The next tick reads it.`
    return `Message ${replied.message_id} on ${key} already says this${answered}; nothing new recorded.`
}

/** What a reload found, as the loop's terminal says it: the keys that changed, when the loop runs on them, and which
 * wait for a restart. */
export function reloadedText(reload: ConfigReload): string {
    const what = reload.changed.length === 0 ? 'Nothing changed' : `${reload.changed.join(', ')} changed`
    const when = reload.after_tick
        ? 'The loop reads it again once the running tick ends.'
        : 'The loop runs on it from now on.'
    const count = reload.restart.length
    const restart =
        count === 0 ? '' : ` ${reload.restart.join(', ')} take${count === 1 ? 's' : ''} effect on a restart.`
    return `${what}. ${when}${restart}`
}
