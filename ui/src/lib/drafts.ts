import type { Draft, DraftStatus, PullRequestThreads, Reaction, ReviewThread } from '@/api/types'
import { place } from '@/lib/reviews'
import type { Placed } from '@/lib/reviews'
import type { Tone } from '@/lib/tone'

/** The most characters a draft's text may hold, the operator's edit included: `MAX_DRAFT_CHARS` in canopy's core. */
export const MAX_DRAFT_CHARS = 4000

/**
 * A draft's status chip's tone (ui/DESIGN.md, "A PR's threads"): one waiting on the operator, or that may have posted,
 * or staged on GitHub for them to submit, in the color of what waits on them; one refused in the failure color; one
 * sending as running; the rest plain.
 */
export const DRAFT_TONE: Record<DraftStatus, Tone> = {
    waiting: 'blocked',
    unconfirmed: 'blocked',
    staged: 'blocked',
    refused: 'failed',
    sending: 'running',
    unchecked: 'plain',
    superseded: 'plain',
    dropped: 'plain',
    sent: 'plain',
}

/** How the page draws a reaction: its emoji, and what a screen reader says for it. */
export interface ReactionLook {
    /** The emoji GitHub shows for it. */
    emoji: string
    /** Its name in words. */
    label: string
}

/**
 * Every reaction GitHub offers on a review comment, by the name canopy and GitHub's API give it. A `Record`, so the
 * typecheck fails if the schema gains one this misses.
 */
export const REACTION_LOOKS: Record<Reaction, ReactionLook> = {
    '+1': { emoji: '👍', label: 'Thumbs up' },
    '-1': { emoji: '👎', label: 'Thumbs down' },
    laugh: { emoji: '😄', label: 'Laugh' },
    hooray: { emoji: '🎉', label: 'Hooray' },
    confused: { emoji: '😕', label: 'Confused' },
    heart: { emoji: '❤️', label: 'Heart' },
    rocket: { emoji: '🚀', label: 'Rocket' },
    eyes: { emoji: '👀', label: 'Eyes' },
}

/** The reactions in the order GitHub's picker shows them. */
export const REACTIONS: Reaction[] = ['+1', '-1', 'laugh', 'hooray', 'confused', 'heart', 'rocket', 'eyes']

/** The reaction a picker's value names, or null for none or a value no reaction has. */
export function reactionOf(value: string): Reaction | null {
    return REACTIONS.find((r) => r === value) ?? null
}

/** Whether the operator can still edit or drop a draft: one waiting, or one no read has checked yet. */
export function open(draft: Pick<Draft, 'status'>): boolean {
    return draft.status === 'waiting' || draft.status === 'unchecked'
}

/** Every draft for the PR a send takes now, in the page's order: the review's body, then each thread's, as placed. */
export function waiting(threads: PullRequestThreads): Draft[] {
    return [...threads.pr_drafts, ...threads.threads.flatMap((t) => t.drafts)].filter((d) => d.status === 'waiting')
}

/** Every draft for the PR in the review the operator staged, which they submit on GitHub. */
export function staged(threads: PullRequestThreads): Draft[] {
    return [...threads.pr_drafts, ...threads.threads.flatMap((t) => t.drafts)].filter((d) => d.status === 'staged')
}

/** Sorts a PR's threads onto its diff: at their line, under their file, or elsewhere, as a review's findings are. */
export function placeThreads(threads: PullRequestThreads): Placed<ReviewThread> {
    return place(threads.threads, (t) => ({ file: t.file, line: t.diff_line }), threads.diff !== null)
}

/** A draft as the head of a PR's threads lists it: where its card sits, so a link can jump to it. */
export interface ListedDraft {
    /** The draft as the server sent it. */
    draft: Draft
    /** Where it goes, in words: its thread's file and line, the review's body, or no thread yet. */
    where: string
    /** The index in the diff of the file its card sits on, or null when it sits on none. */
    file: number | null
}

/**
 * Every draft for the PR in the order the page shows their cards: the review's body, the threads on the diff file by
 * file, those under a file's header before those on a line, then the threads off the diff, then the drafts no read has
 * placed on a thread.
 */
export function listDrafts(threads: PullRequestThreads, placed: Placed<ReviewThread>): ListedDraft[] {
    const listed: ListedDraft[] = threads.pr_drafts.map((draft) => ({ draft, where: "the review's body", file: null }))
    const files = [...new Set([...placed.files.keys(), ...placed.lines.keys()])].toSorted((a, b) => a - b)
    for (const file of files) {
        const onLines = [...(placed.lines.get(file) ?? [])].toSorted(([a], [b]) => a - b)
        for (const thread of [...(placed.files.get(file) ?? []), ...onLines.flatMap(([, onLine]) => onLine)]) {
            listed.push(...threadDrafts(thread, file))
        }
    }
    for (const thread of placed.elsewhere) {
        listed.push(...threadDrafts(thread, null))
    }
    for (const draft of threads.unplaced) {
        listed.push({ draft, where: 'not on a thread', file: null })
    }
    return listed
}

/** Where a thread is, as its card heads with it: its file and line, its file alone, or null when it names no file. */
export function threadWhere(thread: Pick<ReviewThread, 'path' | 'line'>): string | null {
    if (thread.path === null) {
        return null
    }
    return thread.line === null ? thread.path : `${thread.path}:${thread.line}`
}

/** The element id a draft's card has on the page, which the head of the PR's threads links to. */
export function draftAnchor(draft: Pick<Draft, 'run' | 'number'>): string {
    return `draft-${draft.run}-${draft.number}`
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

// A thread's drafts as listed, on the file of the diff its card sits on, or null.
function threadDrafts(thread: ReviewThread, file: number | null): ListedDraft[] {
    const where = threadWhere(thread) ?? 'a thread'
    return thread.drafts.map((draft) => ({ draft, where, file }))
}
