import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useEffectEvent } from 'react'

import { markReviewsSeen, refreshSeen } from '@/api/mutations'
import type { FindingSeverity, ReviewSummary } from '@/api/types'
import { counted } from '@/lib/descriptions'

/**
 * Which reviews' results are new to the operator (DESIGN §22): a review with a result to read is new until they see
 * it, on its page or with `canopy review show ID`, or mark it seen from the reviews list. The server says which have
 * one (`news`): those that found something, and every one the operator asked for; a clean review the loop started on
 * its own has none, so it never pings.
 * The journal keeps what they have seen, so every browser and the CLI agree on it, and the reviews list carries it on
 * each review (`seen`).
 */

/** Whether a review's result is new to the operator: it has one to read, and they have not seen it. */
export function isNew(review: Pick<ReviewSummary, 'news' | 'seen'>): boolean {
    return review.news && !review.seen
}

/** The reviews whose results are new to the operator, in the list's order; none while the list has not arrived. */
export function unseenOf(reviews: readonly ReviewSummary[] | undefined): ReviewSummary[] {
    return reviews === undefined ? [] : reviews.filter((review) => isNew(review))
}

/** The worst finding among new results, which colors their count as it colors a verdict; null when none has one. */
export function worstOf(unseen: readonly ReviewSummary[]): FindingSeverity | null {
    const worst = unseen.map((review) => review.worst)
    if (worst.includes('blocking')) {
        return 'blocking'
    }
    return worst.includes('major') ? 'major' : (worst.find((severity) => severity !== null) ?? null)
}

/** New results in words, for a screen reader and on hover: `1 new review to read`, `3 new reviews to read`. */
export function unseenText(n: number): string {
    return `${counted(n, 'new review')} to read`
}

/**
 * Marking reviews seen, in a component: `mark` marks them seen, and the reviews list says so at once.
 * `pending` while a mark is on its way, and `error` why the last one failed, a refusal naming its guard.
 */
export function useMarkSeen() {
    const client = useQueryClient()
    const marked = useMutation({
        mutationFn: markReviewsSeen,
        onSuccess: (_, runs) => refreshSeen(client, runs),
    })
    return { mark: (runs: number[]) => marked.mutate(runs), pending: marked.isPending, error: marked.error }
}

/**
 * Marks a review seen once a page shows its result, so one the operator watches end is seen as it ends. Once only: a
 * review already seen, or still running, sends nothing.
 */
export function useSeesReview(review: Pick<ReviewSummary, 'id' | 'news' | 'seen'> | undefined): void {
    const { mark } = useMarkSeen()
    const id = review?.id
    const fresh = review !== undefined && isNew(review)
    const see = useEffectEvent((run: number) => mark([run]))
    useEffect(() => {
        if (fresh && id !== undefined) {
            see(id)
        }
    }, [id, fresh])
}
