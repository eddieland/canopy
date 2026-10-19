import type { ReviewSummary } from '@/api/types'
import { pullRequestLabel } from '@/lib/pull-request-label'
import { reviewRef } from '@/lib/refs'
import { verdictText } from '@/lib/reviews'
import type { ToastState } from '@/lib/toast-settings'
import type { NewToast } from '@/lib/toasts'

/**
 * A toast for each review in `after` that moved into a state of `on` since `before`: it started, or it ended clean,
 * with findings, or failed. A review new to the list moved from nothing, so one that started and ended between two
 * lists toasts how it ended. Nothing before the first list, as the page has nothing to compare it with.
 */
export function reviewToasts(
    before: readonly ReviewSummary[] | undefined,
    after: readonly ReviewSummary[],
    on: readonly ToastState<'reviews'>[],
): NewToast[] {
    if (before === undefined || on.length === 0) {
        return []
    }
    const was = new Map(before.map((review) => [review.id, review]))
    return after.flatMap((review) => {
        const state = stateOf(review)
        const prior = was.get(review.id)
        if (state === null || (prior !== undefined && stateOf(prior) === state) || !on.includes(state)) {
            return []
        }
        const text = state === 'failed' ? 'failed' : verdictText(review)
        return [{ title: `${reviewRef(review.id)}: ${text}`, detail: pullRequestLabel(review.pr_url), tone: 'moved' }]
    })
}

// Where a review stands, in the states a toast can announce: None for one that ended done with no verdict.
function stateOf(review: ReviewSummary): ToastState<'reviews'> | null {
    if (review.state === 'running') {
        return 'started'
    }
    if (review.state !== 'done') {
        return 'failed'
    }
    return review.verdict
}
