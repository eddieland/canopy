// The operator's comments on a plan (docs/design/PLANNING.md §25, Commenting on a plan): each a thread on a passage,
// with its replies, open until the operator resolves it. Every function returns a new list and leaves the one it is
// given as it was, so a component keeps the list in state. The open threads become one message to the planner
// (`changeRequest`), which is how the operator asks for changes: the next plan is written with every comment and the
// passage it is on in front of it.
import type { PlanThreadView } from '@/api/types'
import { ATOM, collapse } from '@/lib/plan-anchors'
import type { Anchor } from '@/lib/plan-anchors'

/** How long a comment or a reply may be, as a reply to a ticket may (DESIGN §22). */
export const MAX_COMMENT = 4000

/**
 * How long a change request may be: it is an operator message, so it has a reply's bound (DESIGN §22), which the
 * server enforces. A request over it says so rather than be cut.
 */
export const MAX_REQUEST = 4000

/**
 * The most characters of notes an approval carries to the implement: the server's `plans.MAX_NOTE`, an operator
 * message's bound less the sentence the approval puts before them.
 */
export const MAX_NOTES = 3800

/** How much of a passage a change request quotes: enough to find it, so a long one leaves room for the comments. */
export const MAX_QUOTE = 160

/** One reply in a thread. */
export interface PlanReply {
    /** Its id, unique in its thread. */
    id: string
    /** What it says. */
    body: string
    /** When it was written, as an ISO time. */
    at: string
}

/** A comment on a passage of a plan, and the replies under it. */
export interface PlanThread {
    /** Its id, unique among the plan's threads. */
    id: string
    /** The passage it is on. */
    anchor: Anchor
    /** What the comment says. */
    body: string
    /** When it was written, as an ISO time. */
    at: string
    /** Whether the operator marked it done. A resolved thread is kept, and asks the planner for nothing. */
    resolved: boolean
    /** Its replies, oldest first. */
    replies: PlanReply[]
}

/** `threads` with a new open thread on `anchor` at the end. */
export function addThread(threads: PlanThread[], thread: Omit<PlanThread, 'resolved' | 'replies'>): PlanThread[] {
    return [...threads, { ...thread, resolved: false, replies: [] }]
}

/** `threads` with `reply` at the end of thread `id`'s replies. */
export function addReply(threads: PlanThread[], id: string, reply: PlanReply): PlanThread[] {
    return threads.map((thread) => (thread.id === id ? { ...thread, replies: [...thread.replies, reply] } : thread))
}

/** `threads` with thread `id`'s comment saying `body` instead. */
export function editThread(threads: PlanThread[], id: string, body: string): PlanThread[] {
    return threads.map((thread) => (thread.id === id ? { ...thread, body } : thread))
}

/** `threads` with reply `replyId` of thread `id` saying `body` instead. */
export function editReply(threads: PlanThread[], id: string, replyId: string, body: string): PlanThread[] {
    return threads.map((thread) =>
        thread.id === id
            ? { ...thread, replies: thread.replies.map((reply) => (reply.id === replyId ? { ...reply, body } : reply)) }
            : thread,
    )
}

/** `threads` with thread `id` resolved, or reopened. */
export function setResolved(threads: PlanThread[], id: string, resolved: boolean): PlanThread[] {
    return threads.map((thread) => (thread.id === id ? { ...thread, resolved } : thread))
}

/** `threads` without thread `id`. */
export function removeThread(threads: PlanThread[], id: string): PlanThread[] {
    return threads.filter((thread) => thread.id !== id)
}

/**
 * `threads` with each anchor in `anchors` put on its thread, as the editor finds them after an edit moved or changed
 * their passages. The same list when no anchor changed, so a caller can skip a render that would change nothing.
 */
export function withAnchors(threads: PlanThread[], anchors: ReadonlyMap<string, Anchor>): PlanThread[] {
    const next = threads.map((thread) => {
        const anchor = anchors.get(thread.id)
        return anchor === undefined || sameAnchor(anchor, thread.anchor) ? thread : { ...thread, anchor }
    })
    return next.some((thread, i) => thread !== threads[i]) ? next : threads
}

/** Whether two anchors name the same passage in the same place. */
export function sameAnchor(a: Anchor, b: Anchor): boolean {
    return a.quote === b.quote && a.prefix === b.prefix && a.suffix === b.suffix
}

/**
 * `threads` in the order the plan reads: those found in it by where their passage starts (`starts`, from the editor),
 * then those whose passage is gone, oldest first.
 */
export function inPlanOrder(threads: PlanThread[], starts: ReadonlyMap<string, number>): PlanThread[] {
    const found = threads.filter((thread) => starts.has(thread.id))
    const lost = threads.filter((thread) => !starts.has(thread.id))
    found.sort((a, b) => (starts.get(a.id) ?? 0) - (starts.get(b.id) ?? 0))
    return [...found, ...lost]
}

/** What a change request says when the operator edited the plan's text themselves. */
export const EDITED = 'I edited the plan myself before asking: keep my edits, unless a comment here asks otherwise.'

/**
 * The message that asks the planner for a new plan: each open thread, in plan order, as the passage it is on, the
 * comment, and its replies, then the operator's `note` on the whole plan, if any, and with `edited`, that the operator
 * edited the plan's text. The planner keeps what it was not asked to change, but reads the plan it replaces as its
 * own: this says which words are the operator's. It is the operator's words and the plan's own, so it goes to the
 * planner as an operator message, as a reply does. Empty when there is nothing to ask: no open thread and no note.
 */
export function changeRequest(
    threads: PlanThread[],
    starts: ReadonlyMap<string, number>,
    note = '',
    edited = false,
): string {
    const parts = commented(threads, starts, 'Change the plan where I commented.', note)
    if (edited && parts.length > 0) {
        parts.push(EDITED)
    }
    return parts.join('\n\n')
}

/**
 * The notes an approval carries to the implement (`canopy plan KEY --approve --message`): the open threads and the
 * `note` on the whole plan, as `changeRequest` puts them, for small points that need no new plan. The implement reads
 * the plan as approved, edits included, so this says nothing of them. Empty when there is nothing to send.
 */
export function approvalNotes(threads: PlanThread[], starts: ReadonlyMap<string, number>, note = ''): string {
    return commented(threads, starts, 'Where I commented on the plan, do as I say.', note).join('\n\n')
}

/** The journal's threads (`GET /tickets/{key}/plans`), as the editor holds them: each id the journal's, as text. */
export function fromServer(threads: PlanThreadView[]): PlanThread[] {
    return threads.map((thread) => ({
        id: String(thread.id),
        anchor: { quote: thread.quote, prefix: thread.prefix, suffix: thread.suffix },
        body: thread.body,
        at: thread.at,
        resolved: thread.resolved,
        replies: thread.replies.map((reply) => ({ id: String(reply.id), body: reply.body, at: reply.at })),
    }))
}

/** One write that brings the journal's threads to what the editor holds. */
export type ThreadChange =
    | { kind: 'add'; thread: PlanThread }
    | { kind: 'delete'; id: string }
    | { kind: 'edit'; id: string; body: string }
    | { kind: 'resolve'; id: string; resolved: boolean }
    | { kind: 'reply'; id: string; body: string }
    | { kind: 'edit-reply'; id: string; replyId: string; body: string }

/**
 * The writes that take the threads from `before` to `after`, in order: new threads, then each thread's changes, then
 * deletions. A passage an edit moved is not among them: it is saved with the plan (`movedAnchors`).
 */
export function threadChanges(before: PlanThread[], after: PlanThread[]): ThreadChange[] {
    const was = new Map(before.map((thread) => [thread.id, thread]))
    const now = new Set(after.map((thread) => thread.id))
    const changes: ThreadChange[] = []
    for (const thread of after) {
        const old = was.get(thread.id)
        if (old === undefined) {
            changes.push({ kind: 'add', thread })
            continue
        }
        if (old.body !== thread.body) {
            changes.push({ kind: 'edit', id: thread.id, body: thread.body })
        }
        if (old.resolved !== thread.resolved) {
            changes.push({ kind: 'resolve', id: thread.id, resolved: thread.resolved })
        }
        const replies = new Map(old.replies.map((reply) => [reply.id, reply]))
        for (const reply of thread.replies) {
            const prior = replies.get(reply.id)
            if (prior === undefined) {
                changes.push({ kind: 'reply', id: thread.id, body: reply.body })
            } else if (prior.body !== reply.body) {
                changes.push({ kind: 'edit-reply', id: thread.id, replyId: reply.id, body: reply.body })
            }
        }
    }
    for (const thread of before) {
        if (!now.has(thread.id)) {
            changes.push({ kind: 'delete', id: thread.id })
        }
    }
    return changes
}

/** The threads of `saved`, the journal's, whose passage `held`, the editor's, has since moved or reworded. */
export function movedAnchors(saved: PlanThread[], held: PlanThread[]): PlanThread[] {
    const was = new Map(saved.map((thread) => [thread.id, thread]))
    return held.filter((thread) => {
        const old = was.get(thread.id)
        return old !== undefined && !sameAnchor(old.anchor, thread.anchor)
    })
}

// A passage as the planner reads it: without the placeholders its HTML tags and images stand as in the editor's text,
// which are no characters of the plan, and cut to `MAX_QUOTE` characters, at a word when one ends near the cut.
// Each open thread, in plan order, as the passage it is on, the comment, and its replies, after `lead`, then `note`.
function commented(threads: PlanThread[], starts: ReadonlyMap<string, number>, lead: string, note: string): string[] {
    const open = inPlanOrder(threads, starts).filter((thread) => !thread.resolved)
    const parts: string[] = []
    if (open.length > 0) {
        parts.push(`${lead} Each comment quotes the passage it is on.`)
        open.forEach((thread, i) => {
            const gone = starts.has(thread.id) ? '' : ' (no longer in the plan)'
            const lines = [
                `${i + 1}. On "${cut(thread.anchor.quote)}"${gone}:`,
                indent(thread.body),
                ...thread.replies.map((reply) => indent(`Reply: ${reply.body}`)),
            ]
            parts.push(lines.join('\n'))
        })
    }
    if (note.trim()) {
        parts.push(open.length > 0 ? `On the whole plan:\n${note.trim()}` : note.trim())
    }
    return parts
}

function cut(passage: string): string {
    const quote = collapse(passage.replaceAll(ATOM, ''))
    if (quote.length <= MAX_QUOTE) {
        return quote
    }
    const head = quote.slice(0, MAX_QUOTE)
    const space = head.lastIndexOf(' ')
    return `${space > MAX_QUOTE / 2 ? head.slice(0, space) : head}…`
}

// Every line of `text` indented under its list item, so a comment of several lines stays under its passage.
function indent(text: string): string {
    return text
        .trim()
        .split('\n')
        .map((line) => `   ${line}`)
        .join('\n')
}
