import { QueryClient } from '@tanstack/react-query'
import { cleanup, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { keys } from '@/api/queries'
import type { RequestedReview, ReviewSummary } from '@/api/types'
import { renderRouted, tipOf } from '@/test-utils'

import { ReviewsTable } from './reviews-table'

afterEach(() => {
    cleanup()
})

const REVIEW: ReviewSummary = {
    id: 4,
    pr_url: 'https://github.com/acme/web/pull/88',
    repo: 'web',
    sha: '3f9c2a1b7d0e',
    ticket_key: 'ABC-101',
    title: null,
    state: 'done',
    status: 'ok',
    verdict: 'findings',
    findings: 3,
    worst: 'major',
    worst_count: 1,
    impact: 'high',
    cost_usd: 0.31,
    persona: 'skeptic',
    started_at: '2026-10-08T11:00:00Z',
    ended_at: '2026-10-08T11:04:00Z',
    news: true,
    seen: true,
}

const REQUESTED: RequestedReview = {
    pr_url: 'https://github.com/acme/web/pull/95',
    created_at: '2026-10-08T11:40:00Z',
    channel: 'web',
}

function renderReviews(reviews: ReviewSummary[], pr?: boolean) {
    const client = new QueryClient()
    client.setQueryDefaults(keys.meta, { enabled: false })
    return renderRouted(<ReviewsTable reviews={reviews} pr={pr} />, { client })
}

function renderRequested(requestedLast: boolean) {
    const client = new QueryClient()
    client.setQueryDefaults(keys.meta, { enabled: false })
    return renderRouted(<ReviewsTable reviews={[REVIEW]} requested={[REQUESTED]} requestedLast={requestedLast} />, {
        client,
    })
}

describe('ReviewsTable', () => {
    it('lists a PR asked to be reviewed before any review of it has started, opening its page', async () => {
        await renderRequested(false)
        const row = within(screen.getByTestId(`requested-${REQUESTED.pr_url}`))
        expect(row.getByText('requested')).toBeDefined()
        expect(tipOf(row.getByText('requested'))).toBe('Waiting on the next tick to start its review')
        expect(row.getByRole('link', { name: 'acme/web#95' })).toBeDefined()
        expect(row.queryByRole('link', { name: /^review:/u })).toBeNull()
        // What comes next leads the list, newest first.
        const [first, second] = screen.getAllByRole('listitem')
        expect(first?.dataset.testid).toBe(`requested-${REQUESTED.pr_url}`)
        expect(second?.dataset.testid).toBe('review-4')
    })

    it('puts a requested PR last when the list runs oldest first', async () => {
        await renderRequested(true)
        const rows = screen.getAllByRole('listitem').map((row) => row.dataset.testid)
        expect(rows).toEqual(['review-4', `requested-${REQUESTED.pr_url}`])
    })

    it('opens each review’s page, and says what it found with its worst severity', async () => {
        await renderReviews([REVIEW, { ...REVIEW, id: 5, verdict: 'clean', findings: 0, worst: null, impact: null }])
        expect(screen.getByRole('link', { name: 'review:4' }).getAttribute('href')).toBe('/reviews/4')
        const found = within(screen.getByTestId('review-4'))
        expect(found.getByText('3 findings, 1 major')).toBeDefined()
        expect(found.getByText('high impact')).toBeDefined()
        const clean = within(screen.getByTestId('review-5'))
        expect(clean.getByText('clean')).toBeDefined()
        expect(clean.queryByText(/impact/u)).toBeNull()
    })

    it('names the ticket and the PR, and the commit it read in short', async () => {
        await renderReviews([REVIEW])
        expect(screen.getByRole('link', { name: 'ABC-101' }).getAttribute('href')).toBe('/tickets/ABC-101')
        expect(screen.getByRole('link', { name: 'acme/web#88' })).toBeDefined()
        expect(tipOf(screen.getByText('3f9c2a1'))).toBe('3f9c2a1b7d0e')
    })

    it('names the persona each review wrote in, and nothing for one from before canopy recorded it', async () => {
        await renderReviews([REVIEW, { ...REVIEW, id: 5, persona: null }])
        const named = within(screen.getByTestId('review-4')).getByText('as skeptic')
        expect(tipOf(named)).toBe('The persona it wrote in')
        expect(within(screen.getByTestId('review-5')).queryByText(/^as /u)).toBeNull()
    })

    it('says why a PR canopy only reviews has no ticket', async () => {
        await renderReviews([{ ...REVIEW, ticket_key: null }])
        expect(screen.getByText('none').title).toBe('none: canopy only reviews it')
    })

    it('leaves out the ticket and the PR on the PR’s own page, and says the commit it read was at', async () => {
        await renderReviews([REVIEW], false)
        const row = within(screen.getByTestId('pull-request-review-4'))
        expect(row.getAllByRole('link').map((link) => link.textContent)).toEqual(['review:4'])
        expect(row.getByText('at 3f9c2a1')).toBeDefined()
        expect(row.getByText('as skeptic')).toBeDefined()
    })

    it('marks a review whose result the operator has not seen new, and no other', async () => {
        const running = { ...REVIEW, id: 2, state: 'running', ended_at: null, verdict: null, news: false } as const
        const clean = {
            ...REVIEW,
            id: 1,
            verdict: 'clean',
            findings: 0,
            worst: null,
            news: false,
            seen: false,
        } as const
        await renderReviews([{ ...REVIEW, seen: false }, { ...REVIEW, id: 3 }, { ...running, seen: false }, clean])
        const fresh = within(screen.getByTestId('review-4')).getByText('new')
        expect(tipOf(fresh)).toBe('new: you have not seen it yet')
        // Seen, still running with no result to see, or clean and started by the loop, with nothing to read.
        expect(within(screen.getByTestId('review-3')).queryByText('new')).toBeNull()
        expect(within(screen.getByTestId('review-2')).queryByText('new')).toBeNull()
        expect(within(screen.getByTestId('review-1')).queryByText('new')).toBeNull()
    })
})
