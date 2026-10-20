import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { mockReviews } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { ReviewSummary } from '@/api/types'

import { hasResult, isNew, unseenOf, unseenText, useMarkSeen, useSeesReview, worstOf } from './seen-reviews'

const RUNNING = mockReviews[0] as ReviewSummary

// A review run that ended with `fields`: a clean verdict, not seen, unless they say otherwise.
function ended(id: number, fields: Partial<ReviewSummary> = {}): ReviewSummary {
    return {
        ...RUNNING,
        id,
        status: 'ok',
        state: 'done',
        verdict: 'clean',
        ended_at: '2026-10-08T12:05:00Z',
        seen: false,
        ...fields,
    }
}

// Every mark sent, by the refs it names, and what the server stand-in answers it.
let sent: string[][] = []
let answer: Response | undefined

const server: Middleware = {
    async onRequest({ request }) {
        const { refs } = (await request.json()) as { refs: string[] }
        sent.push(refs)
        return answer ?? Response.json({ refs, new: refs })
    },
}

beforeEach(() => {
    sent = []
    answer = undefined
    api.use(server)
})

afterEach(() => {
    api.eject(server)
})

// A query client holding `reviews` as the reviews list, and fetching nothing.
function withReviews(reviews: ReviewSummary[]) {
    const client = new QueryClient()
    client.setQueryDefaults([], { enabled: false })
    client.setQueryData(keys.reviews, reviews)
    const wrapper = ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    return { client, wrapper }
}

describe('isNew', () => {
    it('is new once ended with a verdict and not seen; a review running, or with no verdict, has no result', () => {
        expect(hasResult(RUNNING)).toBe(false)
        expect(isNew(RUNNING)).toBe(false)
        expect(isNew(ended(6))).toBe(true)
        expect(isNew(ended(6, { seen: true }))).toBe(false)
        expect(isNew(ended(6, { state: 'failed', status: 'unknown', verdict: null }))).toBe(false)
    })

    it('lists the new ones in order, and none before the list arrives', () => {
        const reviews = [RUNNING, ended(8), ended(7, { seen: true }), ended(6)]
        expect(unseenOf(reviews).map((review) => review.id)).toEqual([8, 6])
        expect(unseenOf(undefined)).toEqual([])
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

describe('useMarkSeen', () => {
    it('marks reviews seen by their refs, and the list says so before the stream does', async () => {
        const { client, wrapper } = withReviews([ended(7), ended(6), ended(5)])
        const { result } = renderHook(() => useMarkSeen(), { wrapper })
        act(() => result.current.mark([7, 5]))
        await waitFor(() => {
            expect(unseenOf(client.getQueryData(keys.reviews)).map((review) => review.id)).toEqual([6])
        })
        expect(sent).toEqual([['review:7', 'review:5']])
    })

    it('says why a mark was refused, and marks nothing', async () => {
        answer = Response.json({ detail: { guard: 'running', reason: 'review:7 is still running' } }, { status: 409 })
        const { client, wrapper } = withReviews([ended(7)])
        const { result } = renderHook(() => useMarkSeen(), { wrapper })
        act(() => result.current.mark([7]))
        await waitFor(() => {
            expect(result.current.error).not.toBeNull()
        })
        expect(unseenOf(client.getQueryData(keys.reviews))).toHaveLength(1)
    })
})

describe('useSeesReview', () => {
    it('marks a review seen once its result is shown, not while it runs, and only once', async () => {
        const { wrapper } = withReviews([])
        const { rerender } = renderHook((review: ReviewSummary | undefined) => useSeesReview(review), {
            initialProps: undefined,
            wrapper,
        })
        rerender(RUNNING)
        rerender(ended(RUNNING.id))
        rerender(ended(RUNNING.id))
        await waitFor(() => {
            expect(sent).toEqual([[`review:${RUNNING.id}`]])
        })
        rerender(ended(RUNNING.id, { seen: true }))
        rerender(ended(9, { seen: true }))
        expect(sent).toHaveLength(1)
    })
})
