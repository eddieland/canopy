import type { AttentionItem, TicketSummary } from '@/api/types'
import { splitLinks } from '@/lib/links'
import { pullRequestUrl } from '@/lib/pull-request-label'
import { codeSpans } from '@/lib/rich-text'

/** How urgent an attention item is: the order the attention list shows it in, and its chip's color (DESIGN.md). */
export type Severity = 'failed' | 'waiting' | 'other' | 'finding'

// Reasons a run is refused for its model (DESIGN §13): the runtime does not list the model chosen, or its list could
// not be read. Nothing runs on another model, so the work stays stalled until the operator chooses one or fixes the
// runtime.
const MODEL_REASONS = new Set(['model_missing', 'model_list_failed'])

// What an item refused its model names when no ticket's menu can fix it: the runtime's list, and which of
// `[runtime.models]` it lacks.
const MODELS_COMMAND = 'canopy models'

// Reasons raised because something broke: a run, a run refused its model, a chore, a review, the overseer's `canopy`,
// or the disk (§14). A reason not named here or below, the overseer's phase-table reasons included, is `other`.
const FAILED = new Set([
    ...MODEL_REASONS,
    'crashed',
    'unpushed',
    'unknown_result',
    'worker_failed',
    'attempt_limit',
    'chore_failed',
    'review_failed',
    'review_limit',
    'canopy_unavailable',
    'disk_low',
])

// The reasons a review's draft raises (DESIGN §34): a review the operator asked for, done with its draft unpublished,
// and a draft staged on GitHub or of unknown outcome, until a read settles it.
const REVIEW_DRAFT_REASONS = new Set(['review_waiting', 'review_unsettled'])

// Reasons that wait on the operator's own answer: a private ticket's question or a planner's, an untrusted review's
// go-ahead (D089), a review's rebuttal of a worker's decline or its late finding (DESIGN §21), a plan to approve (§25),
// the replies a run drafted (§29), or a review's draft (§34).
const WAITING = new Set([
    'awaiting_reply',
    'untrusted_review',
    'review_rebuttal',
    'review_late',
    'plan_review',
    'drafts_waiting',
    ...REVIEW_DRAFT_REASONS,
])

// Reasons for a PR that is done for now and waits on someone else: a reviewer, or the merge (DESIGN §7). Nothing is
// stuck while one is open, so they never count as blocking.
const PARKED = new Set(['needs_reviewer', 'ready_to_merge'])

// Reasons raised for a ticket's latest run, or its runs at a limit: what the operator reads first is that run.
const RUN_BROKE = new Set(['worker_failed', 'crashed', 'unpushed', 'unknown_result', 'attempt_limit'])

// The reasons agent memory raises (DESIGN §28), each with the proposals or lessons to act on under its head.
const MEMORY_REASONS = new Set(['memory_proposal', 'lesson_review', 'lesson_wrong'])

// Reasons whose answer is a reply: a question, or the go-ahead an untrusted review waits on (D089).
const ANSWERED_BY_REPLY = new Set(['awaiting_reply', 'untrusted_review'])

// How the overseer's `plan_review` detail names a feedback plan (DESIGN §32), with its id: `feedback plan 3 for ...`.
const FEEDBACK_PLAN = /^feedback plan (\d+)\b/u

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

/**
 * The item to move on to once the operator has answered `current`: the next in `items`, the list in its order, that
 * waits on their answer and is not `done` (answered already), searching on from `current` and then from the top.
 * Null when no other waits on them.
 */
export function nextWaiting(
    items: readonly AttentionItem[],
    current: string,
    done: (item: AttentionItem) => boolean,
): AttentionItem | null {
    const at = items.findIndex((item) => item.id === current)
    const around = [...items.slice(at + 1), ...items.slice(0, Math.max(at, 0))]
    return around.find((item) => item.id !== current && severity(item) === 'waiting' && !done(item)) ?? null
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
 * The list's count split as the nav's badge says it, most severe first, each part only when it holds an item. A
 * finding counts as `other`.
 */
export function breakdown(counts: Record<Severity, number>): BreakdownPart[] {
    const parts: BreakdownPart[] = [
        { kind: 'failed', label: 'broken', count: counts.failed },
        { kind: 'waiting', label: 'waiting on you', count: counts.waiting },
        { kind: 'other', label: 'other', count: counts.other + counts.finding },
    ]
    return parts.filter(({ count }) => count > 0)
}

/** The breakdown in words: `1 broken, 1 waiting on you, 3 other`. */
export function breakdownText(parts: readonly BreakdownPart[]): string {
    return parts.map(({ count, label }) => `${count} ${label}`).join(', ')
}

/**
 * What an item's reason asks of the operator, which picks the first block of its detail, under its head (ui/DESIGN.md,
 * "The attention detail"): the ticket's latest run, for a run that broke; the PR, for one waiting on someone else; the
 * reply, for an answer; the plan's card, for a plan; the PR's page at the plan, for a feedback plan; the proposals or
 * lessons memory's items name; the PR's threads, for the replies a run drafted; the review's page, for a review's
 * draft; the task's page, for a one-off task's item; the ticket's models, for a ticket's run refused its model; the
 * command to run, for an item about nothing canopy shows that names one, or one refused its model about no ticket.
 * `ticket` is any other ticket's item, which leads with the ticket's own actions; `none`, the rest.
 */
export type Ask =
    | 'run'
    | 'pull-request'
    | 'reply'
    | 'plan'
    | 'feedback-plan'
    | 'memory'
    | 'drafts'
    | 'review'
    | 'task'
    | 'model'
    | 'command'
    | 'ticket'
    | 'none'

/**
 * The item's `Ask`. A chore's item and a PR's own are `none`: their detail is the chore's notes, or the PR's limit. A
 * `plan_review` item is a feedback plan's (`feedbackPlanReview`) or a ticket plan's, which `ticket`, its ticket as the
 * tickets list has it, tells apart.
 */
export function ask(item: AttentionItem, ticket?: TicketSummary): Ask {
    if (MEMORY_REASONS.has(item.reason) && !item.finding) {
        return 'memory'
    }
    if (REVIEW_DRAFT_REASONS.has(item.reason) && !item.finding && reviewOf(item) !== null) {
        return 'review'
    }
    // A task's item names `canopy` commands in its detail, but its page is where it is read and answered.
    if (item.task !== null) {
        return 'task'
    }
    // A chore's item too: its notes cannot fix a model, and its runs and the overseer's take theirs from config alone.
    if (modelRefused(item)) {
        return item.ticket_key === null ? 'command' : 'model'
    }
    if (item.ticket_key === null) {
        return item.chore === null && item.pr === null && commandOf(item) !== null ? 'command' : 'none'
    }
    if (RUN_BROKE.has(item.reason)) {
        return 'run'
    }
    if (item.reason === 'drafts_waiting') {
        return 'drafts'
    }
    if (PARKED.has(item.reason)) {
        return 'pull-request'
    }
    if (ANSWERED_BY_REPLY.has(item.reason)) {
        return 'reply'
    }
    if (item.reason !== 'plan_review') {
        return 'ticket'
    }
    return feedbackPlanReview(item, ticket) ? 'feedback-plan' : 'plan'
}

/**
 * Whether a `plan_review` item is a feedback plan's (DESIGN §32) rather than its ticket plan's: the overseer raises
 * both with one reason. Its detail names the plan, so the item stays one once the plan is approved; else `ticket`, its
 * ticket as the tickets list has it, has a feedback plan waiting and no plan of its own that does.
 */
export function feedbackPlanReview(item: AttentionItem, ticket?: TicketSummary): boolean {
    if (feedbackPlanOf(item) !== null) {
        return true
    }
    return ticket !== undefined && ticket.feedback_plan !== null && !ticket.plan_waits
}

/** The feedback plan a `plan_review` item's detail names, by its id, or null when it names none. */
export function feedbackPlanOf(item: AttentionItem): number | null {
    const match = item.reason === 'plan_review' ? FEEDBACK_PLAN.exec(item.detail) : null
    return match?.[1] === undefined ? null : Number(match[1])
}

// What `awaiting_detail` ends an `awaiting_reply` item's detail with, for the CLI's reader (DESIGN §22).
const REPLY_HINT = /; answer with `canopy reply [^`]+`$/u

/** An item's detail as the UI shows it: without the `canopy reply` hint, since the page's reply form is the answer. */
export function shownDetail(item: AttentionItem): string {
    return item.detail.replace(REPLY_HINT, '')
}

/**
 * The `canopy` command an item's detail names in a code span, such as `repo_missing`'s `canopy workspace sync`; for an
 * item refused its model about no ticket that names none, `canopy models`, which says what the runtime lists.
 */
export function commandOf(item: AttentionItem): string | null {
    const command = codeSpans(item.detail).find((piece) => piece.kind === 'code' && piece.text.startsWith('canopy '))
    if (command === undefined && modelRefused(item) && item.ticket_key === null) {
        return MODELS_COMMAND
    }
    return command?.text ?? null
}

/** Whether the item is a run refused its model (`model_missing`, `model_list_failed`), not a chore's finding. */
export function modelRefused(item: AttentionItem): boolean {
    return MODEL_REASONS.has(item.reason) && !item.finding
}

// A review run named as the harness writes one, standing as a word of its own.
const REVIEW_REF = /\breview:(\d+)\b/u

/** The first review run an item's detail names as `review:5`, as a review's draft's items do, or null for none. */
export function reviewOf(item: AttentionItem): number | null {
    const match = REVIEW_REF.exec(item.detail)
    return match?.[1] === undefined ? null : Number(match[1])
}

/**
 * The first PR an item's detail names, as `needs_reviewer`'s does: its own URL, even where the detail links into it, or
 * null when it names none.
 */
export function pullRequestOf(item: AttentionItem): string | null {
    for (const piece of codeSpans(item.detail)) {
        if (piece.kind === 'text') {
            for (const part of splitLinks(piece.text)) {
                const url = part.href === undefined ? null : pullRequestUrl(part.href)
                if (url !== null) {
                    return url
                }
            }
        }
    }
    return null
}
