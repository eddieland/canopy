import type { AttentionItem } from '@/api/types'

/** How urgent an attention item is: the order the attention list shows it in, and its chip's color (DESIGN.md). */
export type Severity = 'failed' | 'waiting' | 'other' | 'finding'

// Reasons raised because something broke: a run, a chore, or a review (DESIGN §14). A reason not named here
// or below, the overseer's phase-table reasons included, is `other`.
const FAILED = new Set([
    'crashed',
    'unpushed',
    'unknown_result',
    'worker_failed',
    'attempt_limit',
    'chore_failed',
    'review_failed',
    'review_limit',
])

// Reasons that wait on the operator's own answer: a private ticket's question, an untrusted review's go-ahead (D089).
const WAITING = new Set(['awaiting_reply', 'untrusted_review'])

const RANK: Record<Severity, number> = { failed: 0, waiting: 1, other: 2, finding: 3 }

/** An item's severity: a finding, a failure, a wait on the operator's answer, or anything else. */
export function severity(item: AttentionItem): Severity {
    if (item.finding) return 'finding'
    if (FAILED.has(item.reason)) return 'failed'
    if (WAITING.has(item.reason)) return 'waiting'
    return 'other'
}

/** How many of the items are of each severity. */
export function countBySeverity(items: AttentionItem[]): Record<Severity, number> {
    const counts: Record<Severity, number> = { failed: 0, waiting: 0, other: 0, finding: 0 }
    for (const item of items) counts[severity(item)] += 1
    return counts
}

/** The items, most severe first; within a severity, the one open longest first. */
export function bySeverity(items: AttentionItem[]): AttentionItem[] {
    return items.toSorted(
        (a, b) =>
            RANK[severity(a)] - RANK[severity(b)] ||
            Date.parse(a.since) - Date.parse(b.since) ||
            a.id.localeCompare(b.id),
    )
}
