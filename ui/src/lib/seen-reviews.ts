import { useEffect } from 'react'

import type { FindingSeverity, ReviewSummary } from '@/api/types'
import { counted } from '@/lib/descriptions'
import { storedSetting, useStoredSetting } from '@/lib/stored-setting'

/**
 * Which reviews' results the operator has seen, in this browser: a review's result is new from when it ends with a
 * verdict until its page shows it, or the reviews panel marks them all seen. The first time a browser reads the
 * reviews, every result already in is taken as seen, so a new browser counts only what ends after, not the last
 * hundred. Kept in localStorage like a list's order, and synced across tabs. Only the latest `MAX_KEPT` ids are kept,
 * so the key stays small: twice the reviews the list holds, so none it shows is dropped.
 */

/** Where localStorage keeps the reviews seen, as a JSON array of their ids, the latest seen last. */
export const STORAGE_KEY = 'canopy-seen-reviews'

/** How many reviews' ids are kept: seeing one more drops the one seen longest ago. */
export const MAX_KEPT = 200

/**
 * The ids as stored, keeping only whole positive numbers. Null when nothing is stored, or nothing readable: this
 * browser has not read the reviews yet, so the first read takes every result in as seen.
 */
export function parseSeen(raw: string | null): number[] | null {
    if (raw === null) {
        return null
    }
    let value: unknown
    try {
        value = JSON.parse(raw)
    } catch {
        return null
    }
    if (!Array.isArray(value)) {
        return null
    }
    return value.filter((id): id is number => Number.isSafeInteger(id) && id > 0)
}

/** Whether a review has a result to see: it ended, and reported a verdict. A run that reported none has nothing. */
export function hasResult(review: Pick<ReviewSummary, 'ended_at' | 'verdict'>): boolean {
    return review.ended_at !== null && review.verdict !== null
}

/** The reviews whose results are new: ended with a verdict and not seen, in the list's order. None before a read. */
export function unseenOf(reviews: readonly ReviewSummary[], seen: readonly number[] | null): ReviewSummary[] {
    if (seen === null) {
        return []
    }
    const known = new Set(seen)
    return reviews.filter((review) => hasResult(review) && !known.has(review.id))
}

/** `seen` with `ids` added, moved to the end as the latest seen, and the oldest past `MAX_KEPT` gone. */
export function withSeen(seen: readonly number[] | null, ids: Iterable<number>): number[] {
    const added = new Set(ids)
    const rest = (seen ?? []).filter((id) => !added.has(id))
    return [...rest, ...added].slice(-MAX_KEPT)
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
 * The reviews whose results are new, from the reviews list as the server sent it; none while it has not arrived.
 * Re-renders when one is seen, from this tab or another. The first list this browser reads takes its results as seen.
 */
export function useUnseenReviews(reviews: ReviewSummary[] | undefined): ReviewSummary[] {
    const seen = useStoredSetting(setting)
    const first = seen === null && reviews !== undefined
    useEffect(() => {
        // Read again rather than trust the render's: another tab may have taken the first read since.
        if (first && setting.get() === null) {
            setting.set(
                withSeen(
                    null,
                    reviews.filter((review) => hasResult(review)).map((review) => review.id),
                ),
            )
        }
    }, [first, reviews])
    return reviews === undefined ? [] : unseenOf(reviews, seen)
}

/**
 * Marks reviews' results seen, stores it, and applies it now, on this tab and the others. Nothing before this browser
 * has read the reviews: that first read takes them as seen, and one marked before it would stop it.
 */
export function markSeen(ids: Iterable<number>): void {
    const seen = setting.get()
    if (seen === null) {
        return
    }
    const marked = [...ids]
    if (marked.every((id) => seen.includes(id))) {
        return
    }
    setting.set(withSeen(seen, marked))
}

/** Marks a review's result seen once a page shows it, so a review the operator watches end is seen as it ends. */
export function useSeesReview(review: Pick<ReviewSummary, 'id' | 'ended_at' | 'verdict'> | undefined): void {
    const id = review?.id
    const shown = review !== undefined && hasResult(review)
    useEffect(() => {
        if (shown && id !== undefined) {
            markSeen([id])
        }
    }, [id, shown])
}

const setting = storedSetting({ key: STORAGE_KEY, parse: parseSeen, serialize: JSON.stringify })
