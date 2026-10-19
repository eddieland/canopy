import { describe, expect, it } from 'vitest'

import { mockReviews } from '@/api/mocks'
import type { ReviewSummary } from '@/api/types'
import { TOAST_STATES } from '@/lib/toast-settings'

import { reviewToasts } from './review-toasts'

const all = TOAST_STATES.reviews

function review(fields: Partial<ReviewSummary>): ReviewSummary {
    const [base] = mockReviews
    if (!base) {
        throw new Error('no mock review')
    }
    return { ...base, ...fields }
}

const running = review({})
const clean = review({ status: 'done', state: 'done', verdict: 'clean' })
const found = review({
    status: 'done',
    state: 'done',
    verdict: 'findings',
    findings: 3,
    worst: 'major',
    worst_count: 1,
})
const failed = review({ status: 'timeout', state: 'failed' })

describe('reviewToasts', () => {
    it('toasts a review starting, with its PR under it', () => {
        expect(reviewToasts([], [running], ['started'])).toEqual([
            { title: 'review:4: reviewing', detail: 'acme/web#12', tone: 'moved' },
        ])
    })

    it('toasts how a review ended, in the words its verdict uses', () => {
        expect(reviewToasts([running], [clean], all)).toEqual([
            { title: 'review:4: clean', detail: 'acme/web#12', tone: 'moved' },
        ])
        expect(reviewToasts([running], [found], all)).toEqual([
            { title: 'review:4: 3 findings, 1 major', detail: 'acme/web#12', tone: 'moved' },
        ])
        expect(reviewToasts([running], [failed], all)).toEqual([
            { title: 'review:4: failed', detail: 'acme/web#12', tone: 'moved' },
        ])
    })

    it('toasts a review that started and ended between two lists as it ended', () => {
        expect(reviewToasts([], [found], ['started', 'findings']).map((t) => t.title)).toEqual([
            'review:4: 3 findings, 1 major',
        ])
    })

    it('says nothing of a state turned off, a review that stayed, or anything before the first list', () => {
        expect(reviewToasts([running], [clean], ['findings', 'failed'])).toEqual([])
        expect(reviewToasts([clean], [clean], all)).toEqual([])
        expect(reviewToasts([running], [running], all)).toEqual([])
        expect(reviewToasts(undefined, [running], all)).toEqual([])
    })

    it('says nothing of a review that ended done with no verdict', () => {
        expect(reviewToasts([running], [review({ status: 'done', state: 'done' })], all)).toEqual([])
    })
})
