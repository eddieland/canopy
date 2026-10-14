import type { FindingSeverity, ReviewFinding, ReviewSummary } from '@/api/types'

/**
 * A severity chip's classes, written out in full so Tailwind finds them. A blocking finding reads as broken work, a
 * major one as waiting on the operator, as the attention list's reasons do; a minor one is plain (ui/DESIGN.md, "A
 * review").
 */
export const SEVERITY_TEXT: Record<FindingSeverity, string> = {
    blocking: 'text-status-failed border-status-failed/40',
    major: 'text-status-blocked border-status-blocked/40',
    minor: '',
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

/** What a review found, in a few words: `clean`, `3 findings`, or the status of a run that reported no verdict. */
export function verdictText(review: ReviewSummary): string {
    if (review.verdict === 'clean') {
        return 'clean'
    }
    if (review.verdict === 'findings') {
        return review.findings === 1 ? '1 finding' : `${review.findings} findings`
    }
    return review.state === 'running' ? 'reviewing' : 'no verdict'
}

/** A commit as a page shows it: its first 7 characters, as git and GitHub do. */
export function shortSha(sha: string): string {
    return sha.slice(0, 7)
}

/** Where a review's findings sit in its diff: by file and line, on a file's header, or nowhere in the diff. */
export interface Placed {
    /** File index, then line, to the findings anchored on that line, in the review's order. */
    lines: Map<number, Map<number, Numbered[]>>
    /** File index to the findings about that file whose line the diff does not show, or that name no line. */
    files: Map<number, Numbered[]>
    /** The findings about no file in the diff, or every finding when there is no diff. */
    elsewhere: Numbered[]
}

/** A finding with its number in the review, from 1, which its card and the findings list both show. */
export interface Numbered {
    /** The finding's number in the review, from 1. */
    n: number
    /** The finding as the server sent it. */
    finding: ReviewFinding
}

/** Sorts a review's findings onto the diff: by file and line, onto a file's header, or elsewhere. */
export function placeFindings(findings: ReviewFinding[], hasDiff: boolean): Placed {
    const placed: Placed = { lines: new Map(), files: new Map(), elsewhere: [] }
    findings.forEach((finding, i) => {
        const numbered = { n: i + 1, finding }
        if (!hasDiff || finding.file === null) {
            placed.elsewhere.push(numbered)
        } else if (finding.line === null) {
            placed.files.set(finding.file, [...(placed.files.get(finding.file) ?? []), numbered])
        } else {
            const byLine = placed.lines.get(finding.file) ?? new Map<number, Numbered[]>()
            byLine.set(finding.line, [...(byLine.get(finding.line) ?? []), numbered])
            placed.lines.set(finding.file, byLine)
        }
    })
    return placed
}

/** The element id a finding's card has on the page, which the findings list links to. */
export function findingAnchor(n: number): string {
    return `finding-${n}`
}
