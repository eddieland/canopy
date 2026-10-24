import type { FindingSeverity, ReviewFinding, ReviewSummary } from '@/api/types'
import type { Tone } from '@/lib/tone'

/**
 * A severity chip's tone. A blocking finding reads as broken work, a major one as waiting on the operator, as the
 * attention list's reasons do; a minor one is plain (ui/DESIGN.md, "A review").
 */
export const SEVERITY_TONE: Record<FindingSeverity, Tone> = {
    blocking: 'failed',
    major: 'blocked',
    minor: 'plain',
}

// Written out so Tailwind finds them: a verdict wears its worst finding's color, as that finding's chip does.
const VERDICT_TEXT: Record<FindingSeverity, string> = {
    blocking: 'text-status-failed',
    major: 'text-status-blocked',
    minor: '',
}

/**
 * A verdict's text color, by the worst finding the review reported, not by how its run ended (its dot says that): a
 * blocking finding's in the failure color, a major one's in the color of what waits on the operator, and anything else
 * plain, a clean review included.
 */
export function verdictTone(review: Pick<ReviewSummary, 'worst'>): string {
    return review.worst === null ? '' : VERDICT_TEXT[review.worst]
}

/**
 * What a review found, in a few words, its worst severity among them, since its color alone would not say it:
 * `clean`, `3 findings, 1 major`, `1 blocking finding` when every finding is that bad, or the status of a run that
 * reported no verdict.
 */
export function verdictText(review: ReviewSummary): string {
    if (review.verdict === 'clean') {
        return 'clean'
    }
    if (review.verdict === 'findings') {
        const noun = review.findings === 1 ? 'finding' : 'findings'
        if (review.worst === null) {
            return `${review.findings} ${noun}`
        }
        if (review.worst_count === review.findings) {
            return `${review.findings} ${review.worst} ${noun}`
        }
        return `${review.findings} ${noun}, ${review.worst_count} ${review.worst}`
    }
    return review.state === 'running' ? 'reviewing' : 'no verdict'
}

/** A commit as a page shows it: its first 7 characters, as git and GitHub do. */
export function shortSha(sha: string): string {
    return sha.slice(0, 7)
}

/**
 * Reviews in groups, each a request's reviews of one commit in its personas, side by side as the request form
 * promised: a group sits where its first review is in `reviews`, its others after it in their own order. Every other
 * review is a group of one, so the list keeps its order but for pulling a request's reviews together.
 */
export function requestGroups<T extends Pick<ReviewSummary, 'request_id' | 'sha'>>(reviews: readonly T[]): T[][] {
    const groups: T[][] = []
    const byRequest = new Map<string, T[]>()
    for (const review of reviews) {
        const key = requestOf(review)
        const found = key === null ? undefined : byRequest.get(key)
        if (found === undefined) {
            const group = [review]
            groups.push(group)
            if (key !== null) {
                byRequest.set(key, group)
            }
        } else {
            found.push(review)
        }
    }
    return groups
}

/** The reviews among `runs` that `review`'s request made of its commit in its other personas, `review` left out. */
export function siblingsOf<T extends Pick<ReviewSummary, 'id' | 'request_id' | 'sha'>>(
    review: T,
    runs: readonly T[],
): T[] {
    const key = requestOf(review)
    return key === null ? [] : runs.filter((r) => r.id !== review.id && requestOf(r) === key)
}

// A key the reviews one request made of one commit share, one in each persona the operator chose for it (DESIGN §31);
// null for a review the loop started on its own, which answers no request.
function requestOf(review: Pick<ReviewSummary, 'request_id' | 'sha'>): string | null {
    return review.request_id === null ? null : `${review.request_id} ${review.sha}`
}

/** Where cards sit on a diff: by file and line, on a file's header, or nowhere in the diff. */
export interface Placed<T> {
    /** File index, then line, to the cards anchored on that line, in their order. */
    lines: Map<number, Map<number, T[]>>
    /** File index to the cards about that file whose line the diff does not show, or that name no line. */
    files: Map<number, T[]>
    /** The cards about no file in the diff, or every card when there is no diff. */
    elsewhere: T[]
}

/** A finding with its number in the review, from 1, which its card and the findings list both show. */
export interface Numbered {
    /** The finding's number in the review, from 1. */
    n: number
    /** The finding as the server sent it. */
    finding: ReviewFinding
}

/**
 * Sorts cards onto a diff by where each one is: its file's index and its new-side line, or a null file for none in the
 * diff and a null line for one the diff does not show. Every card is elsewhere when there is no diff.
 */
export function place<T>(
    items: T[],
    at: (item: T) => { file: number | null; line: number | null },
    hasDiff: boolean,
): Placed<T> {
    const placed: Placed<T> = { lines: new Map(), files: new Map(), elsewhere: [] }
    for (const item of items) {
        const { file, line } = at(item)
        if (!hasDiff || file === null) {
            placed.elsewhere.push(item)
        } else if (line === null) {
            placed.files.set(file, [...(placed.files.get(file) ?? []), item])
        } else {
            const byLine = placed.lines.get(file) ?? new Map<number, T[]>()
            byLine.set(line, [...(byLine.get(line) ?? []), item])
            placed.lines.set(file, byLine)
        }
    }
    return placed
}

/** Sorts a review's findings onto the diff: by file and line, onto a file's header, or elsewhere. */
export function placeFindings(findings: ReviewFinding[], hasDiff: boolean): Placed<Numbered> {
    return place(
        findings.map((finding, i) => ({ n: i + 1, finding })),
        ({ finding }) => finding,
        hasDiff,
    )
}

/** The element id a finding's card has on the page, which the findings list links to. */
export function findingAnchor(n: number): string {
    return `finding-${n}`
}

/** The id of a review thread's card on the PR's page, which a feedback plan's item links to, by the thread's id. */
export function threadAnchor(id: string): string {
    return `thread-${id}`
}
