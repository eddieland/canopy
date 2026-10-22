import type { ReviewDraft, ReviewDraftComment, ReviewDraftVersion } from '@/api/types'
import type { Numbered, Placed } from '@/lib/reviews'
import type { Tone } from '@/lib/tone'

/**
 * A review's draft's status chip's tone (DESIGN §34): one staged on GitHub, or that may have posted, waits on the
 * operator; one posting now is running; the rest, a draft they need never publish among them, are plain.
 */
export const REVIEW_DRAFT_TONE: Record<ReviewDraft['status'], Tone> = {
    waiting: 'plain',
    publishing: 'running',
    unconfirmed: 'blocked',
    staged: 'blocked',
    published: 'plain',
}

/**
 * A review's draft's state as a list's chip says it (`ReviewDraftChip`): one that waits on the operator is a `draft`,
 * as they would call it, and the rest keep the journal's word.
 */
export const REVIEW_DRAFT_WORD: Record<ReviewDraft['status'], string> = {
    waiting: 'draft',
    publishing: 'publishing',
    unconfirmed: 'unconfirmed',
    staged: 'staged',
    published: 'published',
}

/** What each state of a review's draft means for the operator, on its chip's hover after the journal's word. */
export const REVIEW_DRAFT_MEANS: Record<ReviewDraft['status'], string> = {
    waiting: 'yours to edit and publish; nothing is on GitHub yet',
    publishing: 'posting to GitHub now',
    unconfirmed: 'a publish may have posted; the next read of the PR says',
    staged: 'a pending review on GitHub, for you to submit there',
    published: 'posted on GitHub',
}

/** A line of the diff the operator is writing a new comment on: the file's index and path, and the new-side line. */
export interface Adding {
    /** The file's index in the diff. */
    file: number
    /** The file's path, as the diff names it. */
    path: string
    /** The line, on the diff's new side. */
    line: number
}

/** What sits on a review's diff: one of its findings, a comment of its draft, or the form of a new comment. */
export type ReviewCard =
    | { kind: 'finding'; numbered: Numbered }
    | { kind: 'comment'; comment: ReviewDraftComment }
    | { kind: 'new'; adding: Adding }

/**
 * Puts the operator's own comments of the draft, and the new comment being written, on the diff beside the findings:
 * on a line, each after the findings there. A comment made from a finding is that finding's card (`ReviewPointCard`),
 * one card per point, so it is not placed again. A comment always sits on a line of the diff the review kept; one
 * placed nowhere, once the diff is gone, is elsewhere.
 */
export function placeReviewCards(
    findings: Placed<Numbered>,
    comments: readonly ReviewDraftComment[],
    adding: Adding | null,
): Placed<ReviewCard> {
    const placed: Placed<ReviewCard> = {
        lines: new Map(
            [...findings.lines].map(([file, byLine]) => [
                file,
                new Map([...byLine].map(([line, items]) => [line, asCards(items)])),
            ]),
        ),
        files: new Map([...findings.files].map(([file, items]) => [file, asCards(items)])),
        elsewhere: asCards(findings.elsewhere),
    }
    const onLine = (file: number, line: number, card: ReviewCard) => {
        const byLine = placed.lines.get(file) ?? new Map<number, ReviewCard[]>()
        byLine.set(line, [...(byLine.get(line) ?? []), card])
        placed.lines.set(file, byLine)
    }
    for (const comment of comments.filter((c) => c.finding === null)) {
        const card: ReviewCard = { kind: 'comment', comment }
        if (comment.file === null) {
            placed.elsewhere.push(card)
        } else if (comment.diff_line === null) {
            placed.files.set(comment.file, [...(placed.files.get(comment.file) ?? []), card])
        } else {
            onLine(comment.file, comment.diff_line, card)
        }
    }
    if (adding !== null) {
        onLine(adding.file, adding.line, { kind: 'new', adding })
    }
    return placed
}

// Findings as cards on a review's diff.
function asCards(items: Numbered[]): ReviewCard[] {
    return items.map((numbered) => ({ kind: 'finding', numbered }))
}

/** The element id a draft's comment's card has on the page, which the draft's list of comments links to. */
export function commentAnchor(number: number): string {
    return `draft-comment-${number}`
}

/**
 * Where a review's finding stands in its draft (DESIGN §34): a comment carries it, the body holds it where no line of
 * the diff took it, or it is left out, dismissed or its comment dropped.
 */
export type PointState = { kind: 'comment'; comment: ReviewDraftComment } | { kind: 'body' } | { kind: 'out' }

/** Where finding `n` stands in `draft`: the comment made from it, the body, or neither. */
export function pointState(draft: Pick<ReviewDraft, 'comments' | 'in_body'>, n: number): PointState {
    const comment = draft.comments.find((c) => c.finding === n)
    if (comment !== undefined) {
        return { kind: 'comment', comment }
    }
    return draft.in_body.includes(n) ? { kind: 'body' } : { kind: 'out' }
}

/** Which of a review's `findings` findings its draft leaves out, by number, from 1. */
export function leftOut(draft: Pick<ReviewDraft, 'comments' | 'in_body'>, findings: number): number[] {
    return Array.from({ length: findings }, (_, i) => i + 1).filter((n) => pointState(draft, n).kind === 'out')
}

/** Who wrote a version, as `canopy review draft` says it: the reviewer, a revision, or the operator, and where. */
export function versionBy(version: Pick<ReviewDraftVersion, 'author' | 'channel'>): string {
    switch (version.author) {
        case 'reviewer': {
            return 'by the reviewer'
        }
        case 'reviser': {
            return 'by a revision'
        }
        case 'operator': {
            return `by you through ${version.channel ?? 'canopy'}`
        }
    }
}

/** Whether the operator may still change or publish a draft: only while it waits, before any publish claimed it. */
export function editable(draft: Pick<ReviewDraft, 'status'>): boolean {
    return draft.status === 'waiting'
}

/** The most characters a note on a draft may hold, after trimming: the operator's bound in canopy's core. */
export const MAX_NOTE_CHARS = 4000

/**
 * Where a draft's revisions stand (DESIGN §34): one running, which holds a note and a publish until it ends; spent,
 * past its limit, `asked` when a note still waits on a grant; a note asking the next tick for one; or none asked.
 */
export type RevisionStanding =
    | { kind: 'running'; run: number }
    | { kind: 'spent'; asked: boolean }
    | { kind: 'asked' }
    | { kind: 'open' }

/** The fields of a draft its revisions' standing reads. */
type Revisable = Pick<ReviewDraft, 'status' | 'notes' | 'revisions' | 'revision_limit'>

/** Where `draft`'s revisions stand, in the order canopy refuses a note: a revision running first, then the limit. */
export function revisionStanding(draft: Revisable): RevisionStanding {
    const running = draft.revisions.find((revision) => revision.state === 'running')
    if (running !== undefined) {
        return { kind: 'running', run: running.id }
    }
    const asked = editable(draft) && draft.notes.length > 0
    if (draft.revisions.length >= draft.revision_limit) {
        return { kind: 'spent', asked }
    }
    return asked ? { kind: 'asked' } : { kind: 'open' }
}
