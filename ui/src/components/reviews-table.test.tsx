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
    request_id: null,
    started_at: '2026-10-08T11:00:00Z',
    ended_at: '2026-10-08T11:04:00Z',
    news: true,
    seen: true,
    draft: null,
    served: [],
}

const REQUESTED: RequestedReview = {
    pr_url: 'https://github.com/acme/web/pull/95',
    created_at: '2026-10-08T11:40:00Z',
    channel: 'web',
    author: 'dana',
}

function renderReviews(reviews: ReviewSummary[], pr?: boolean) {
    const client = new QueryClient()
    client.setQueryDefaults(keys.meta, { enabled: false })
    return renderRouted(<ReviewsTable reviews={reviews} pr={pr} />, { client })
}

/** The text `word` in review `id`'s row. */
function chip(id: number, word: string) {
    return within(screen.getByTestId(`review-${id}`)).getByText(word)
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

    it('names a requested PR’s author where its ticket would be, and says none until canopy has read it', async () => {
        await renderRequested(false)
        const row = within(screen.getByTestId(`requested-${REQUESTED.pr_url}`))
        expect(tipOf(row.getByText('dana'))).toBe("The PR's author: canopy only reviews it, so it has no ticket")
        expect(row.queryByText('none')).toBeNull()
        cleanup()
        const client = new QueryClient()
        client.setQueryDefaults(keys.meta, { enabled: false })
        await renderRouted(<ReviewsTable reviews={[]} requested={[{ ...REQUESTED, author: null }]} />, { client })
        expect(screen.getByText('none').title).toBe('none: canopy only reviews it')
    })

    it('says where each review’s draft stands after its verdict, and nothing for one without a draft', async () => {
        await renderReviews([
            { ...REVIEW, id: 1, draft: 'waiting' },
            { ...REVIEW, id: 2, draft: 'staged' },
            { ...REVIEW, id: 3, draft: 'unconfirmed' },
            { ...REVIEW, id: 6, draft: 'published' },
            REVIEW,
        ])
        expect(tipOf(chip(1, 'draft'))).toBe('waiting: yours to edit and publish; nothing is on GitHub yet')
        expect(tipOf(chip(2, 'staged'))).toBe('staged: a pending review on GitHub, for you to submit there')
        expect(tipOf(chip(3, 'unconfirmed'))).toBe(
            'unconfirmed: a publish may have posted; the next read of the PR says',
        )
        expect(tipOf(chip(6, 'published'))).toBe('published: posted on GitHub')
        const none = within(screen.getByTestId('review-4'))
        expect(none.queryByText(/^(draft|staged|unconfirmed|published)$/u)).toBeNull()
    })

    it('puts a requested PR last when the list runs oldest first', async () => {
        await renderRequested(true)
        const rows = screen.getAllByRole('listitem').map((row) => row.dataset.testid)
        expect(rows).toEqual(['review-4', `requested-${REQUESTED.pr_url}`])
    })

    it('opens each review’s page, and says what it found with its worst severity', async () => {
        await renderReviews([REVIEW, { ...REVIEW, id: 5, verdict: 'clean', findings: 0, worst: null, impact: null }])
        expect(screen.getByRole('link', { name: 'review:4' }).getAttribute('href')).toBe('/pull-requests/reviews/4')
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

    it('names the PR’s title after the PR, and nothing for a PR without one', async () => {
        await renderReviews([
            { ...REVIEW, title: 'Debounce search input' },
            { ...REVIEW, id: 5, ticket_key: null },
        ])
        expect(within(screen.getByTestId('review-4')).getByText('Debounce search input')).toBeDefined()
        const untitled = within(screen.getByTestId('review-5'))
        expect(untitled.queryByText('untitled')).toBeNull()
        expect(untitled.queryByText('Debounce search input')).toBeNull()
    })

    it('leaves the title to the lead of a request’s group, and off the PR’s own page', async () => {
        const asked = { ...REVIEW, title: 'Debounce search input', request_id: 3 }
        await renderReviews([
            { ...asked, id: 9 },
            { ...asked, id: 7, persona: 'canopy' },
        ])
        expect(within(screen.getByTestId('review-9')).getByText('Debounce search input')).toBeDefined()
        expect(within(screen.getByTestId('review-7')).queryByText('Debounce search input')).toBeNull()
        cleanup()
        await renderReviews([asked], false)
        expect(screen.queryByText('Debounce search input')).toBeNull()
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

    it("sets a request's reviews in several personas together, each after the first named by its persona", async () => {
        const asked = { ...REVIEW, ticket_key: null, request_id: 3 }
        await renderReviews([
            { ...asked, id: 9, persona: 'skeptic' },
            { ...REVIEW, id: 8 },
            { ...asked, id: 7, persona: 'canopy' },
        ])
        const ids = screen.getAllByRole('listitem').map((row) => row.dataset.testid)
        expect(ids).toEqual(['review-9', 'review-7', 'review-8'])
        // The lead names the PR and its commit; the next only its persona, the PR and commit being the lead's.
        const next = within(screen.getByTestId('review-7'))
        expect(next.getAllByRole('link').map((link) => link.textContent)).toEqual(['review:7'])
        expect(tipOf(next.getByText('as canopy'))).toBe(
            'Reviewed from the same request, of the same commit, as review:9, in another persona',
        )
        expect(next.queryByText('none')).toBeNull()
        expect(within(screen.getByTestId('review-9')).getByRole('link', { name: 'acme/web#88' })).toBeDefined()
    })

    it("groups a request's reviews on the PR's own page too", async () => {
        const asked = { ...REVIEW, request_id: 3 }
        await renderReviews(
            [
                { ...asked, id: 9 },
                { ...REVIEW, id: 8, request_id: 2 },
                { ...asked, id: 7 },
            ],
            false,
        )
        const ids = screen.getAllByRole('listitem').map((row) => row.dataset.testid)
        expect(ids).toEqual(['pull-request-review-9', 'pull-request-review-7', 'pull-request-review-8'])
        expect(within(screen.getByTestId('pull-request-review-7')).queryByText('at 3f9c2a1')).toBeNull()
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
