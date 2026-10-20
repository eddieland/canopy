import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { mockReviews } from '@/api/mocks'
import type { ReviewSummary } from '@/api/types'
import { otherTab } from '@/test-utils'

import { hasResult, MAX_KEPT, parseSeen, unseenOf, unseenText, withSeen, worstOf } from './seen-reviews'

// The reviews seen are read when the module loads, so each test loads a fresh copy.
function load() {
    vi.resetModules()
    return import('./seen-reviews')
}

const RUNNING = mockReviews[0] as ReviewSummary

// A review run that ended with `fields`: a clean verdict unless they say otherwise.
function ended(id: number, fields: Partial<ReviewSummary> = {}): ReviewSummary {
    return {
        ...RUNNING,
        id,
        status: 'ok',
        state: 'done',
        verdict: 'clean',
        ended_at: '2026-10-08T12:05:00Z',
        ...fields,
    }
}

describe('parseSeen', () => {
    it('reads the reviews stored, and nothing read yet when nothing is', () => {
        expect(parseSeen('[2,7]')).toEqual([2, 7])
        expect(parseSeen('[]')).toEqual([])
        expect(parseSeen(null)).toBeNull()
    })

    it('keeps only whole positive numbers, and reads anything unreadable as not read yet', () => {
        expect(parseSeen('[2,"3",-1,0,1.5,null,9]')).toEqual([2, 9])
        expect(parseSeen('{"2":true}')).toBeNull()
        expect(parseSeen('not json')).toBeNull()
    })
})

describe('unseenOf', () => {
    it('counts the results not seen: a review still running, or ended with no verdict, has none', () => {
        const reviews = [RUNNING, ended(6), ended(7, { state: 'failed', status: 'failed', verdict: null }), ended(8)]
        expect(hasResult(RUNNING)).toBe(false)
        expect(unseenOf(reviews, [8]).map((review) => review.id)).toEqual([6])
    })

    it('counts none before this browser has read the reviews', () => {
        expect(unseenOf([ended(6)], null)).toEqual([])
    })
})

describe('withSeen', () => {
    it('adds the reviews seen, moving one seen again to the end', () => {
        expect(withSeen(null, [4])).toEqual([4])
        expect(withSeen([2, 4], [2, 9])).toEqual([4, 2, 9])
    })

    it('drops the one seen longest ago past the limit', () => {
        const full = Array.from({ length: MAX_KEPT }, (_, i) => i + 1)
        const kept = withSeen(full, [1000])
        expect(kept).toHaveLength(MAX_KEPT)
        expect(kept[0]).toBe(2)
        expect(kept.at(-1)).toBe(1000)
    })
})

describe('worstOf', () => {
    it('takes the worst finding among the new results, or none when none found anything', () => {
        expect(worstOf([ended(1, { worst: 'minor' }), ended(2, { worst: 'blocking' }), ended(3)])).toBe('blocking')
        expect(worstOf([ended(1, { worst: 'minor' }), ended(2, { worst: 'major' })])).toBe('major')
        expect(worstOf([ended(1, { worst: 'minor' })])).toBe('minor')
        expect(worstOf([ended(1)])).toBeNull()
    })
})

describe('unseenText', () => {
    it('says how many are new', () => {
        expect(unseenText(1)).toBe('1 new review to read')
        expect(unseenText(3)).toBe('3 new reviews to read')
    })
})

describe('useUnseenReviews', () => {
    beforeEach(() => localStorage.clear())

    it("takes the first list's results as seen, then counts each that ends after until it is seen", async () => {
        const seen = await load()
        const { result, rerender } = renderHook(
            (reviews: ReviewSummary[] | undefined) => seen.useUnseenReviews(reviews),
            {
                initialProps: undefined,
            },
        )
        expect(result.current).toEqual([])
        // Nothing is stored until the list arrives: a review marked seen before it would stop that first read.
        act(() => seen.markSeen([3]))
        expect(localStorage.getItem(seen.STORAGE_KEY)).toBeNull()

        rerender([RUNNING, ended(3)])
        expect(result.current).toEqual([])
        expect(localStorage.getItem(seen.STORAGE_KEY)).toBe('[3]')

        // The review that was running ends, and another with it.
        const now = [ended(RUNNING.id), ended(6, { verdict: 'findings', findings: 1, worst: 'major' }), ended(3)]
        rerender(now)
        expect(result.current.map((review) => review.id)).toEqual([RUNNING.id, 6])

        act(() => seen.markSeen([6]))
        expect(result.current.map((review) => review.id)).toEqual([RUNNING.id])
        expect(localStorage.getItem(seen.STORAGE_KEY)).toBe('[3,6]')
    })

    it('takes an empty first list as read, so the first result to end is new', async () => {
        const seen = await load()
        const none: ReviewSummary[] = []
        const { result, rerender } = renderHook((reviews: ReviewSummary[]) => seen.useUnseenReviews(reviews), {
            initialProps: none,
        })
        expect(localStorage.getItem(seen.STORAGE_KEY)).toBe('[]')
        rerender([ended(6)])
        expect(result.current.map((review) => review.id)).toEqual([6])
    })

    it('follows the reviews another tab saw', async () => {
        localStorage.setItem('canopy-seen-reviews', '[]')
        const seen = await load()
        const { result } = renderHook(() => seen.useUnseenReviews([ended(6), ended(7)]))
        expect(result.current).toHaveLength(2)
        act(() => otherTab(seen.STORAGE_KEY, '[7]'))
        expect(result.current.map((review) => review.id)).toEqual([6])
    })
})

describe('useSeesReview', () => {
    beforeEach(() => localStorage.setItem('canopy-seen-reviews', '[]'))

    it('marks a review seen once its result is shown, not while it runs', async () => {
        const seen = await load()
        const { rerender } = renderHook((review: ReviewSummary | undefined) => seen.useSeesReview(review), {
            initialProps: undefined,
        })
        rerender(RUNNING)
        expect(localStorage.getItem(seen.STORAGE_KEY)).toBe('[]')
        rerender(ended(RUNNING.id))
        expect(localStorage.getItem(seen.STORAGE_KEY)).toBe(`[${RUNNING.id}]`)
    })
})
