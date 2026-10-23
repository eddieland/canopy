import { QueryClient } from '@tanstack/react-query'
import { act, cleanup, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { mockChores, mockReviews, mockRuns } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { ChoreSummary, Meta, ReviewSummary, Run, Spend } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { RailFooter, RailSpend, RailWorking } from './rail'

const [RUNNING, BLOCKED] = mockRuns as [Run, Run]

beforeEach(() => {
    // The rows' ages read the clock: hold it three minutes after the running run started.
    vi.useFakeTimers({ toFake: ['Date'], now: new Date('2026-10-08T12:03:00Z') })
})

afterEach(() => {
    cleanup()
    vi.useRealTimers()
})

// A query client holding what the test seeds under `key`, or nothing yet, and fetching nothing.
function seeded(key: readonly string[], data: unknown) {
    const client = new QueryClient()
    client.setQueryDefaults(key, { enabled: false })
    if (data !== undefined) {
        client.setQueryData(key, data)
    }
    return client
}

// A query client holding the runs, the reviews, and the chores the rail reads, or no runs yet, and fetching nothing.
function rail(runs: Run[] | undefined, reviews: ReviewSummary[] = [], chores: ChoreSummary[] = []) {
    const client = seeded(keys.runs, runs)
    client.setQueryDefaults(keys.reviews, { enabled: false })
    client.setQueryDefaults(keys.chores, { enabled: false })
    client.setQueryData(keys.reviews, reviews)
    client.setQueryData(keys.chores, chores)
    return client
}

// Follows `link`, and lets the navigation settle.
async function follow(link: HTMLElement) {
    await act(async () => {
        fireEvent.click(link)
        await Promise.resolve()
    })
}

// A running run on its own ticket, started `minutes` after noon.
function running(id: number, minutes: number): Run {
    const started = `2026-10-08T12:0${minutes}:00Z`
    return { ...RUNNING, id, ticket_key: `ABC-${id}`, started_at: started }
}

describe('RailWorking', () => {
    it('lists no rows and no count before the runs arrive', async () => {
        await renderRouted(<RailWorking />, { client: rail(undefined) })
        const working = screen.getByRole('region', { name: 'Working' })
        expect(within(working).queryByRole('link')).toBeNull()
        expect(within(working).queryByText(/^\d+$/u)).toBeNull()
        expect(within(working).queryByText('nothing working now')).toBeNull()
    })

    it('says nothing is working now, and counts none, when every run has ended', async () => {
        const ended: Run = { ...RUNNING, status: 'ok', state: 'done', ended_at: '2026-10-08T12:30:00Z' }
        await renderRouted(<RailWorking />, { client: rail([ended]) })
        const working = screen.getByRole('region', { name: 'Working' })
        expect(within(working).getByText('nothing working now')).toBeDefined()
        expect(within(working).getByText('0')).toBeDefined()
    })

    it('lists the runs running before those waiting on the operator, each opening its page', async () => {
        const { router } = await renderRouted(<RailWorking />, { client: rail([BLOCKED, RUNNING]) })
        const rows = within(screen.getByRole('region', { name: 'Working' })).getAllByRole('link')
        expect(rows.map((row) => row.title)).toEqual(['run:41 implement', 'run:42 implement'])
        const [first, second] = rows as [HTMLElement, HTMLElement]
        expect(within(first).getByText('ABC-101')).toBeDefined()
        expect(within(first).getByText('Sign in with SSO')).toBeDefined()
        expect(within(first).getByText('3m')).toBeDefined()
        expect(within(second).getByText('ABC-102')).toBeDefined()
        expect(within(second).getByText('waiting on you')).toBeDefined()

        await follow(second)
        expect(router.state.location.pathname).toBe('/runs/42')
    })

    it('lists a review of a PR and a chore run running among the runs, each opening its page', async () => {
        const [chore] = mockChores as [ChoreSummary]
        const latest = chore.latest as NonNullable<ChoreSummary['latest']>
        // The chore run started first, then the worker run, then the review.
        const started = '2026-10-08T11:58:00Z'
        const run = { ...latest, id: 3, status: 'running', state: 'running', started_at: started } as const
        const chores = [{ ...chore, running: run }]
        const { router } = await renderRouted(<RailWorking />, {
            client: rail([RUNNING], mockReviews, chores),
        })
        const region = screen.getByRole('region', { name: 'Working' })
        const rows = within(region).getAllByRole('link')
        expect(rows.map((row) => row.title)).toEqual(['chore:deps#3', 'run:41 implement', 'review:5 of acme/web#91'])
        expect(within(region).getByText('3')).toBeDefined()
        const [first, , third] = rows as [HTMLElement, HTMLElement, HTMLElement]
        expect(within(first).getByText('deps')).toBeDefined()
        expect(within(first).getByText('chore run #3')).toBeDefined()
        expect(within(first).getByText('5m')).toBeDefined()
        expect(within(third).getByText('acme/web#91')).toBeDefined()
        expect(within(third).getByText('review:5 · ABC-103')).toBeDefined()
        expect(within(third).getByText('2m')).toBeDefined()

        await follow(third)
        expect(router.state.location.pathname).toBe('/reviews/5')
        await follow(first)
        expect(router.state.location.pathname).toBe('/chores/deps/runs/3')
    })

    it('lists four, then how many more, which opens the runs page; the count is of them all', async () => {
        const runs = [1, 2, 3, 4, 5, 6].map((n) => running(n, n))
        const { router } = await renderRouted(<RailWorking />, { client: rail(runs) })
        const working = screen.getByRole('region', { name: 'Working' })
        expect(within(working).getAllByRole('link', { name: /^ABC-/u })).toHaveLength(4)
        expect(within(working).getByText('6')).toBeDefined()

        await follow(within(working).getByRole('link', { name: '+2 more' }))
        expect(router.state.location.href).toBe('/runs')
    })
})

describe('RailSpend', () => {
    const SPEND: Spend = {
        day: { hours: 24, since: '2026-10-07T12:03:00Z', cost_usd: 1.5 },
        month: { hours: 720, since: '2026-09-08T12:03:00Z', cost_usd: null },
        total_usd: 12,
    }

    it("shows each window's cost after its name, a dash where nothing reported one", async () => {
        await renderRouted(<RailSpend />, { client: seeded(keys.spend, SPEND) })
        expect(screen.getByRole('link', { name: '24h $1.50' })).toBeDefined()
        expect(screen.getByRole('link', { name: '30d –' })).toBeDefined()
        expect(screen.getByTitle('none reported').textContent).toBe('–')
    })

    it('shows no cost before the spend arrives', async () => {
        await renderRouted(<RailSpend />, { client: seeded(keys.spend, undefined) })
        expect(screen.getByRole('link', { name: '24h' })).toBeDefined()
        expect(screen.getByRole('link', { name: '30d' })).toBeDefined()
    })

    it.each([
        ['24h', '/spend?hours=24'],
        ['30d', '/spend?days=30'],
    ])("opens the spend page's breakdown over the %s window", async (window, href) => {
        const { router } = await renderRouted(<RailSpend />, { client: seeded(keys.spend, SPEND) })
        await follow(screen.getByRole('link', { name: new RegExp(`^${window}`, 'u') }))
        expect(router.state.location.href).toBe(href)
    })
})

describe('RailFooter', () => {
    const META: Meta = {
        branch_urls: {},
        build: 'abc123',
        mock: false,
        ticket_url: null,
        version: '0.4.0+abc123',
        workspace_root: '/w',
        repos: ['repo'],
    }

    it('names the version canopy serves once it is known', async () => {
        const { unmount } = await renderRouted(<RailFooter />, { client: seeded(keys.meta, undefined) })
        expect(screen.queryByText(/^canopy/u)).toBeNull()
        unmount()

        await renderRouted(<RailFooter />, { client: seeded(keys.meta, META) })
        expect(screen.getByText('canopy 0.4.0+abc123')).toBeDefined()
    })

    it('opens the guide', async () => {
        const { router } = await renderRouted(<RailFooter />, { client: seeded(keys.meta, META) })
        await follow(screen.getByRole('link', { name: 'Guide' }))
        expect(router.state.location.pathname).toBe('/guide')
    })

    it('opens Settings', async () => {
        const { router } = await renderRouted(<RailFooter />, { client: seeded(keys.meta, META) })
        await follow(screen.getByRole('link', { name: 'Settings' }))
        expect(router.state.location.pathname).toBe('/settings')
    })
})
