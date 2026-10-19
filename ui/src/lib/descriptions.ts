// What a detail page's description says: its subject's state, never what every page of its kind shows, which is the
// title's help (ui/DESIGN.md, the detail skeleton). Each is the facts known, joined as one line: `done · implement`.

import type { ChoreRun, Limit, PullRequest, ReviewSummary, Run, Tick } from '@/api/types'
import { stuck } from '@/lib/limits'
import { reviewRef, runRef } from '@/lib/refs'
import { verdictText } from '@/lib/reviews'
import { NO_TICKET, readable } from '@/lib/words'

/** A run's page: how it ended, its kind, and its ticket, as `done · implement · ABC-099`. */
export function runDescription(run: Pick<Run, 'status' | 'kind' | 'ticket_key'>): string {
    return line(readable(run.status), readable(run.kind), run.ticket_key)
}

/**
 * A review's page: how it ended, alone. Its panel leads with what it found, then its verdict and the commit it read,
 * each said there once (ui/DESIGN.md, "A review").
 */
export function reviewDescription(review: Pick<ReviewSummary, 'status'>): string {
    return readable(review.status)
}

/**
 * A PR's page: where it stands, as its row on the PRs list leads with it. Its latest review and that review's verdict,
 * `review:4 3 findings, 1 major`, or `not reviewed`; `at its review limit` while it is; the run working it now; and,
 * for a PR with no ticket, why, which its identity panel then leaves out. Its ticket and phase are said elsewhere on
 * the page, and its reviews are counted in their panel's header.
 */
export function pullRequestDescription(
    pr: Pick<PullRequest, 'ticket_key' | 'running_run' | 'latest_review'>,
    limit: Limit | null,
): string {
    const review = pr.latest_review
    const reviewed = review === null ? 'not reviewed' : `${reviewRef(review.id)} ${verdictText(review)}`
    const atLimit = limit !== null && stuck([limit]).length > 0 ? 'at its review limit' : null
    const running = pr.running_run === null ? null : `${runRef(pr.running_run)} running`
    return line(reviewed, atLimit, running, pr.ticket_key === null ? NO_TICKET : null)
}

/** A chore run's page: how it ended and, for one that ended `ok`, how many findings it listed and how many more not. */
export function choreRunDescription(run: Pick<ChoreRun, 'status' | 'more_findings'>, findings: number): string {
    const ok = run.status === 'ok'
    const more = ok && run.more_findings > 0 ? `${run.more_findings} not listed` : null
    return line(readable(run.status), ok ? counted(findings, 'finding') : null, more)
}

/** A tick's page: how it ended, how many decisions it recorded, and what woke the loop for it. */
export function tickDescription(tick: Pick<Tick, 'status' | 'woken_by'>, decisions: number): string {
    const woken = tick.woken_by === null ? null : `woken by ${tick.woken_by}`
    return line(readable(tick.status), counted(decisions, 'decision'), woken)
}

/** How many of a noun, in words: `no reviews`, `1 review`, `3 reviews`. */
export function counted(n: number, noun: string): string {
    if (n === 0) {
        return `no ${noun}s`
    }
    return n === 1 ? `1 ${noun}` : `${n} ${noun}s`
}

function line(...parts: (string | null)[]): string {
    return parts.filter((p) => p !== null && p !== '').join(' · ')
}
