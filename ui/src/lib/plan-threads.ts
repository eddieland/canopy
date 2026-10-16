// The operator's comments on a plan (docs/design/PLANNING.md §25, Commenting on a plan): each a thread on a passage,
// with its replies, open until the operator resolves it. Every function returns a new list and leaves the one it is
// given as it was, so a component keeps the list in state. The open threads become one message to the planner
// (`changeRequest`), which is how the operator asks for changes: the next plan is written with every comment and the
// passage it is on in front of it.
import type { Anchor } from '@/lib/plan-anchors'

/** How long a comment or a reply may be, as a reply to a ticket may (DESIGN §22). */
export const MAX_COMMENT = 4000

/**
 * How long a change request may be: it is an operator message, so it has a reply's bound (DESIGN §22), which the
 * server enforces. A request over it says so rather than be cut.
 */
export const MAX_REQUEST = 4000

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

/**
 * The message that asks the planner for a new plan: each open thread, in plan order, as the passage it is on, the
 * comment, and its replies, then the operator's `note` on the whole plan, if any. It is the operator's words and the
 * plan's own, so it goes to the planner as an operator message, as a reply does. Empty when there is nothing to ask:
 * no open thread and no note.
 */
export function changeRequest(threads: PlanThread[], starts: ReadonlyMap<string, number>, note = ''): string {
    const open = inPlanOrder(threads, starts).filter((thread) => !thread.resolved)
    const parts: string[] = []
    if (open.length > 0) {
        parts.push('Change the plan where I commented. Each comment quotes the passage it is on.')
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
    return parts.join('\n\n')
}

// A passage cut to `MAX_QUOTE` characters, at a word when one ends near the cut.
function cut(quote: string): string {
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
