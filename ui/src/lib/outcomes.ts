import type { Replied, Started, Stopped } from '@/api/types'

// What each of the operator's actions did, in the words the CLI's verb prints (canopy/cli/conversation.py).

export function startedText(key: string, started: Started): string {
    const state = started.already ? 'was already started' : 'is started'
    const head = `${key} ${state}, privately: workers read it and write nothing to it.`
    if (started.running_run === null) return `${head} The next tick picks it up.`
    const kind = started.running_private
        ? 'private'
        : 'public, dispatched before this start, so it may write to the ticket'
    return `${head} Run ${started.running_run} (${kind}) is still working it.`
}

export function stoppedText(key: string, stopped: Stopped, now: boolean): string {
    const head = `${key} ${stopped.already ? 'was already stopped' : 'is stopped'}; nothing dispatches it now.`
    if (stopped.running_run === null) return head
    if (!now) return `${head} Run ${stopped.running_run} is still working it and will finish.`
    return stopped.ended
        ? `${head} Run ${stopped.running_run} was ended and its slots returned.`
        : `${head} Run ${stopped.running_run} had already ended.`
}

export function repliedText(key: string, replied: Replied): string {
    const answered = replied.answers !== null ? `, answering message ${replied.answers}` : ''
    if (replied.new) return `Recorded message ${replied.message_id} on ${key}${answered}. The next tick reads it.`
    return `Message ${replied.message_id} on ${key} already says this${answered}; nothing new recorded.`
}
