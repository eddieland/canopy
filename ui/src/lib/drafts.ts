import type { Draft, DraftStatus, PullRequestThreads, ReviewThread } from '@/api/types'
import { place } from '@/lib/reviews'
import type { Placed } from '@/lib/reviews'
import type { Tone } from '@/lib/tone'

/** The most characters a draft's text may hold, the operator's edit included: `MAX_DRAFT_CHARS` in canopy's core. */
export const MAX_DRAFT_CHARS = 4000

/**
 * A draft's status chip's tone (ui/DESIGN.md, "A PR's threads"): one waiting on the operator, or that may have posted,
 * in the color of what waits on them; one refused in the failure color; one sending as running; the rest plain.
 */
export const DRAFT_TONE: Record<DraftStatus, Tone> = {
    waiting: 'blocked',
    unconfirmed: 'blocked',
    refused: 'failed',
    sending: 'running',
    unchecked: 'plain',
    superseded: 'plain',
    dropped: 'plain',
    sent: 'plain',
}

/** Whether the operator can still edit or drop a draft: one waiting, or one no read has checked yet. */
export function open(draft: Pick<Draft, 'status'>): boolean {
    return draft.status === 'waiting' || draft.status === 'unchecked'
}

/** Every draft for the PR a send takes now, in the page's order: the review's body, then each thread's, as placed. */
export function waiting(threads: PullRequestThreads): Draft[] {
    return [...threads.pr_drafts, ...threads.threads.flatMap((t) => t.drafts)].filter((d) => d.status === 'waiting')
}

/** Sorts a PR's threads onto its diff: at their line, under their file, or elsewhere, as a review's findings are. */
export function placeThreads(threads: PullRequestThreads): Placed<ReviewThread> {
    return place(threads.threads, (t) => ({ file: t.file, line: t.diff_line }), threads.diff !== null)
}

/**
 * The PR's head when its diff is not the run's, which the page says, since the threads may sit on lines it no longer
 * has: the head as last read, or null when the two agree or either is not known.
 */
export function movedHead(threads: Pick<PullRequestThreads, 'head_sha' | 'diff_head'>): string | null {
    const { head_sha: head, diff_head: kept } = threads
    return head !== null && kept !== null && head !== kept ? head : null
}

/** How many characters a text holds as canopy counts them, by code point, as the bound does. */
export function draftChars(text: string): number {
    // oxlint-disable-next-line typescript/no-misused-spread -- code points are what the bound counts, as Python's len.
    return [...text].length
}
