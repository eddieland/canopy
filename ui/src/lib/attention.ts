import type { AttentionItem } from '@/api/types'
import { splitLinks } from '@/lib/links'
import { isPullRequest } from '@/lib/pull-request-label'
import { codeSpans } from '@/lib/rich-text'

/** How urgent an attention item is: the order the attention list shows it in, and its chip's color (DESIGN.md). */
export type Severity = 'failed' | 'waiting' | 'other' | 'finding'

// Reasons raised because something broke: a run, a chore, a review, or the overseer's `canopy` (DESIGN §14). A
// reason not named here or below, the overseer's phase-table reasons included, is `other`.
const FAILED = new Set([
    'crashed',
    'unpushed',
    'unknown_result',
    'worker_failed',
    'attempt_limit',
    'chore_failed',
    'review_failed',
    'review_limit',
    'canopy_unavailable',
])

// Reasons that wait on the operator's own answer: a private ticket's question or a planner's, an untrusted review's
// go-ahead (D089), or a plan to approve (DESIGN §25).
const WAITING = new Set(['awaiting_reply', 'untrusted_review', 'plan_review'])

// Reasons for a PR that is done for now and waits on someone else: a reviewer, or the merge (DESIGN §7). Nothing is
// stuck while one is open, so they never count as blocking.
const PARKED = new Set(['needs_reviewer', 'ready_to_merge'])

// Reasons raised for a ticket's latest run, or its runs at a limit: what the operator reads first is that run.
const RUN_BROKE = new Set(['worker_failed', 'crashed', 'unpushed', 'unknown_result', 'attempt_limit'])

// The reasons agent memory raises (DESIGN §28), each with the proposals or lessons to act on under its head.
const MEMORY_REASONS = new Set(['memory_proposal', 'lesson_review', 'lesson_wrong'])

// Reasons whose answer is a reply: a question, or the go-ahead an untrusted review waits on (D089).
const ANSWERED_BY_REPLY = new Set(['awaiting_reply', 'untrusted_review'])

const RANK: Record<Severity, number> = { failed: 0, waiting: 1, other: 2, finding: 3 }

/** An item's severity: a finding, a failure, a wait on the operator's answer, or anything else. */
export function severity(item: AttentionItem): Severity {
    if (item.finding) {
        return 'finding'
    }
    if (FAILED.has(item.reason)) {
        return 'failed'
    }
    if (WAITING.has(item.reason)) {
        return 'waiting'
    }
    return 'other'
}

/**
 * Whether the item holds work up until the operator acts: anything but a chore's finding, which reports, or a PR
 * that waits on a reviewer or its merge.
 */
export function blocking(item: AttentionItem): boolean {
    return !item.finding && !PARKED.has(item.reason)
}

/** How many of the items are of each severity. */
export function countBySeverity(items: AttentionItem[]): Record<Severity, number> {
    const counts: Record<Severity, number> = { failed: 0, waiting: 0, other: 0, finding: 0 }
    for (const item of items) {
        counts[severity(item)] += 1
    }
    return counts
}

/** The items, most severe first; within a severity, the one open longest first. */
export function bySeverity(items: AttentionItem[]): AttentionItem[] {
    return items.toSorted((a, b) => {
        const rank = RANK[severity(a)] - RANK[severity(b)]
        if (rank !== 0) {
            return rank
        }
        const age = Date.parse(a.since) - Date.parse(b.since)
        return age === 0 ? a.id.localeCompare(b.id) : age
    })
}

/** One part of the attention list's count: what is broken, what waits on the operator's answer, or the rest. */
export interface BreakdownPart {
    /** Which part: the failure color's, the operator's, or the muted rest, chores' findings among them. */
    kind: 'failed' | 'waiting' | 'other'
    /** The part's words, the same wherever the count is said: `broken`, `waiting on you`, `other`. */
    label: string
    /** How many items it holds, never 0. */
    count: number
}

/**
 * The list's count split as the Attention counter and the nav's badge both say it, most severe first, each part only
 * when it holds an item. A finding counts as `other`.
 */
export function breakdown(counts: Record<Severity, number>): BreakdownPart[] {
    const parts: BreakdownPart[] = [
        { kind: 'failed', label: 'broken', count: counts.failed },
        { kind: 'waiting', label: 'waiting on you', count: counts.waiting },
        { kind: 'other', label: 'other', count: counts.other + counts.finding },
    ]
    return parts.filter(({ count }) => count > 0)
}

/** The breakdown in words: `1 broken, 1 waiting on you, 3 other`, or `nothing` when the list is empty. */
export function breakdownText(parts: readonly BreakdownPart[]): string {
    return parts.length === 0 ? 'nothing' : parts.map(({ count, label }) => `${count} ${label}`).join(', ')
}

/**
 * What an item's reason asks of the operator, which picks the first block of its detail, under its head (ui/DESIGN.md,
 * "The attention detail"): the ticket's latest run, for a run that broke; the PR, for one waiting on someone else; the
 * reply, for an answer; the plan's card, for a plan; the proposals or lessons memory's items name; the command to run,
 * for an item about nothing canopy shows that names one. `ticket` is any other ticket's item, which leads with the
 * ticket's own actions; `none`, the rest.
 */
export type Ask = 'run' | 'pull-request' | 'reply' | 'plan' | 'memory' | 'command' | 'ticket' | 'none'

/** The item's `Ask`. A chore's item and a PR's own are `none`: their detail is the chore's notes, or the PR's limit. */
export function ask(item: AttentionItem): Ask {
    if (MEMORY_REASONS.has(item.reason) && !item.finding) {
        return 'memory'
    }
    if (item.ticket_key === null) {
        return item.chore === null && item.pr === null && commandOf(item) !== null ? 'command' : 'none'
    }
    if (RUN_BROKE.has(item.reason)) {
        return 'run'
    }
    if (PARKED.has(item.reason)) {
        return 'pull-request'
    }
    if (ANSWERED_BY_REPLY.has(item.reason)) {
        return 'reply'
    }
    return item.reason === 'plan_review' ? 'plan' : 'ticket'
}

// What `awaiting_detail` ends an `awaiting_reply` item's detail with, for the CLI's reader (DESIGN §22).
const REPLY_HINT = /; answer with `canopy reply [^`]+`$/u

/** An item's detail as the UI shows it: without the `canopy reply` hint, since the page's reply form is the answer. */
export function shownDetail(item: AttentionItem): string {
    return item.detail.replace(REPLY_HINT, '')
}

/** The `canopy` command an item's detail names in a code span, such as `repo_missing`'s `canopy workspace sync`. */
export function commandOf(item: AttentionItem): string | null {
    const command = codeSpans(item.detail).find((piece) => piece.kind === 'code' && piece.text.startsWith('canopy '))
    return command?.text ?? null
}

/** The first PR an item's detail names, as `needs_reviewer`'s does: its URL, or null when it names none. */
export function pullRequestOf(item: AttentionItem): string | null {
    for (const piece of codeSpans(item.detail)) {
        if (piece.kind === 'text') {
            const found = splitLinks(piece.text).find((part) => part.href !== undefined && isPullRequest(part.href))
            if (found?.href !== undefined) {
                return found.href
            }
        }
    }
    return null
}
