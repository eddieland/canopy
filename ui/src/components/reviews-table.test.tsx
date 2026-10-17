import { QueryClient } from '@tanstack/react-query'
import { cleanup, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { keys } from '@/api/queries'
import type { ReviewSummary } from '@/api/types'
import { renderRouted } from '@/test-utils'

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
    state: 'done',
    status: 'ok',
    verdict: 'findings',
    findings: 3,
    worst: 'major',
    worst_count: 1,
    impact: 'high',
    cost_usd: 0.31,
    started_at: '2026-10-08T11:00:00Z',
    ended_at: '2026-10-08T11:04:00Z',
}

function renderReviews(reviews: ReviewSummary[], pr?: boolean) {
    const client = new QueryClient()
    client.setQueryDefaults(keys.meta, { enabled: false })
    return renderRouted(<ReviewsTable reviews={reviews} pr={pr} />, { client })
}

describe('ReviewsTable', () => {
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
        expect(screen.getByText('3f9c2a1').title).toBe('3f9c2a1b7d0e')
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
    })
})
