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
 * Puts the draft's comments, and the new comment being written, on the diff beside the findings: on a line, each after
 * the findings there. A comment always sits on a line of the diff the review kept; one placed nowhere, once the diff
 * is gone, is elsewhere.
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
    for (const comment of comments) {
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
