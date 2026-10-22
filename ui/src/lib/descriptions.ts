// What a detail page's description says: its subject's state, never what every page of its kind shows, which is the
// title's help (ui/DESIGN.md, the detail skeleton). Each is the facts known, joined as one line: `done · implement`.

import type {
    ChoreRun,
    Limit,
    PullRequest,
    ReviewDraft,
    ReviewSummary,
    Run,
    Tick,
    TicketPlans,
    TicketSummary,
} from '@/api/types'
import { stuck } from '@/lib/limits'
import { planWaits } from '@/lib/plan-state'
import { pullRequestLabel } from '@/lib/pull-request-label'
import { reviewRef, runRef } from '@/lib/refs'
import { verdictText } from '@/lib/reviews'
import { NO_TICKET, readable, runKind } from '@/lib/words'

/**
 * A run's page: how it ended and its kind, with a resume's reasons, as `done · implement`. The page follows it with
 * its ticket's key as a link, `done · implement · ABC-099`, the one place the page names the ticket.
 */
export function runDescription(run: Pick<Run, 'status' | 'kind' | 'reasons'>): string {
    return line(readable(run.status), readable(runKind(run)))
}

/**
 * A review's page: how it ended, alone. Its panel leads with what it found, then its verdict and the commit it read,
 * each said there once (ui/DESIGN.md, "A review").
 */
export function reviewDescription(review: Pick<ReviewSummary, 'status'>): string {
    return readable(review.status)
}

/**
 * A review's page with a draft: whose review it is, `Your review of acme/api#14 by carol`, or of the PR alone while
 * canopy has not read who opened it. That page is the draft's record, so its title leads with the draft.
 */
export function reviewDraftTitle(prUrl: string, draft: Pick<ReviewDraft, 'pr_author'>): string {
    const pr = pullRequestLabel(prUrl)
    return draft.pr_author === null ? `Your review of ${pr}` : `Your review of ${pr} by ${draft.pr_author}`
}

// What each status of a draft means for the operator, after its chip in the page's description.
const DRAFT_STATE: Record<ReviewDraft['status'], string> = {
    waiting: 'posts nothing until you publish it',
    publishing: 'posting on GitHub now',
    unconfirmed: "may have posted: canopy's next read of the PR settles it",
    staged: 'pending on GitHub, for you to submit there',
    published: 'posted on GitHub',
}

/**
 * A review's page with a draft: the draft's version and what its status means, as `version 3 · posts nothing until
 * you publish it`. The page puts the status's chip ahead of it; the review's own status heads the reviewer's fold.
 */
export function reviewDraftDescription(draft: Pick<ReviewDraft, 'status' | 'version'>): string {
    return line(`version ${draft.version}`, DRAFT_STATE[draft.status])
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

/**
 * A ticket's page: where it stands now, the run working it and the question waiting on the operator, then its plan's
 * status while it has one or needs one, as `run:41 running · plan waiting on you`. Its phase, branch, and what its
 * runs cost are its Work panel's fields; whether it is public or private, its title's chip. Empty when it has none of
 * these; the page follows it with when the ticket was last active.
 */
export function ticketDescription(
    ticket: Pick<TicketSummary, 'running_run' | 'awaiting'>,
    plans: TicketPlans | undefined,
): string {
    const running = ticket.running_run === null ? null : `${runRef(ticket.running_run)} running`
    const waiting = ticket.awaiting === null ? null : 'waiting on you'
    return line(running, waiting, plans === undefined ? null : planWords(plans))
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

// A plan's status in words, as its card's chip says it, or null for a ticket that has no plan and needs none.
function planWords(plans: TicketPlans): string | null {
    const newest = plans.newest?.plan
    if (newest === undefined) {
        return plans.needed ? 'plan needed' : null
    }
    return planWaits(plans) ? 'plan waiting on you' : `plan ${newest.status}`
}
