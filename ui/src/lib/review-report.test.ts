import { describe, expect, it } from 'vitest'

import type { ReviewsDay, ReviewsPullRequest } from '@/api/types'
import type { Clock } from '@/lib/clock'

import {
    canopyReviewerFigures,
    draftsHint,
    resumesPerPlan,
    apartText,
    approvedText,
    dismissalText,
    reviewsBars,
    reviewsDayHint,
    reviewsLine,
    reviewsWindow,
    WAIT_SERIES,
} from './review-report'

const H24: Clock = { hours: '24', zone: false }

function day(name: string, firstReviews: number[], median: number | null = null): ReviewsDay {
    return { day: name, start: `${name}T00:00:00Z`, first_reviews: firstReviews, median_wait_hours: median }
}

// A PR row, only its count mattering to the line.
const PR: ReviewsPullRequest = {
    url: 'https://github.com/acme/web/pull/7',
    ticket_key: 'PROJ-1',
    phase: null,
    waiting_since: null,
    first_review_at: null,
    first_review_hours: null,
    reviews: 1,
    changes_requested: 0,
    comments: 0,
    rounds: 0,
    cost_usd: null,
    ready_at: null,
    merged_at: null,
    hours_to_merge: null,
    approved: 0,
    approved_at: null,
    rounds_to_approval: null,
}

describe('review-report', () => {
    it('offers the week and 30 days, as the health and CI pages do', () => {
        expect(reviewsWindow({ days: '30' })).toEqual({ days: 30 })
        expect(reviewsWindow({ days: 7 })).toEqual({ days: 7 })
        expect(reviewsWindow({ days: '14' })).toBeUndefined()
    })

    it("says the window's state: its reviews, its PRs, and the median first review", () => {
        expect(reviewsLine({ days: 30, reviews: 38, pull_requests: [PR, PR], median_first_review_hours: 4 })).toBe(
            '38 reviews on 2 PRs · median first review 4.0h over 30 days',
        )
        expect(reviewsLine({ days: 7, reviews: 1, pull_requests: [PR], median_first_review_hours: null })).toBe(
            '1 review on 1 PR · no first review timed over 7 days',
        )
    })

    it('says what the median leaves out, and what still waits', () => {
        expect(apartText({ untimed: 0, waiting: 0 })).toBe('')
        expect(apartText({ untimed: 1, waiting: 0 })).toBe(
            '1 reviewed PR had no ready time from GitHub and is left out.',
        )
        expect(apartText({ untimed: 2, waiting: 3 })).toBe(
            '2 reviewed PRs had no ready time from GitHub and are left out. 3 open PRs wait on a first review.',
        )
    })

    it("stacks a day's first reviews by wait, the quickest at the bottom, and names them on hover", () => {
        const [bar] = reviewsBars([day('2026-10-07', [1, 2, 0, 0], 1.5)], H24)
        expect(bar?.total).toBe(3)
        expect(bar?.segments.map((s) => s.fill)).toEqual(WAIT_SERIES.map((s) => s.fill))
        expect(bar?.hint).toBe('Oct 7: 3 first reviews, median 1.5h; under 1h 1, 1–4h 2')
        expect(reviewsDayHint(day('2026-10-08', [0, 0, 0, 0]), H24)).toBe('Oct 8: no first reviews')
    })

    it('says how a plan went ahead, and why a finding was dismissed', () => {
        expect(approvedText({ approved_channel: 'planner' })).toBe('the planner')
        expect(approvedText({ approved_channel: 'cli' })).toBe('you, from the CLI')
        expect(approvedText({ approved_channel: null })).toBe('not approved')
        expect(dismissalText('not_worth_it')).toBe('not worth it')
        expect(dismissalText(null)).toBe('no reason given')
    })
})

describe('resumesPerPlan', () => {
    it('divides the resumes among the plans, and says 0 of an effort with none', () => {
        expect(resumesPerPlan({ plans: 2, resumes: 3 })).toBe(1.5)
        expect(resumesPerPlan({ plans: 0, resumes: 0 })).toBe(0)
    })
})

describe('canopyReviewerFigures and draftsHint', () => {
    const found = {
        review_runs: [
            { purpose: 'own', status: 'done', runs: 2, cost_usd: 0.5 },
            { purpose: 'request', status: 'failed', runs: 1, cost_usd: null },
        ],
        dismissals: [
            { reason: 'wrong', findings: 2 },
            { reason: null, findings: 1 },
        ],
        drafts: [
            { status: 'published', drafts: 1 },
            { status: 'discarded', drafts: 2 },
        ],
    }

    it('sums the runs, their cost where reported, the dismissals, and the drafts made and published', () => {
        expect(canopyReviewerFigures(found)).toEqual({ runs: 3, costUsd: 0.5, dismissed: 3, published: 1, drafted: 3 })
        expect(canopyReviewerFigures({ review_runs: [], dismissals: [], drafts: [] }).costUsd).toBeNull()
    })

    it('says where the drafts stand, or that none was made', () => {
        expect(draftsHint(found)).toBe('Of 3 drafts made: published 1, discarded 2')
        expect(draftsHint({ drafts: [] })).toBe('The drafts of its reviews published to GitHub: none was made')
    })
})
