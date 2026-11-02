import { QueryClient } from '@tanstack/react-query'
import { act, cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockRuns, mockTickets } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { Pause, Run, RunsSince, Tick, TicketSummary } from '@/api/types'
import { StreamContext } from '@/hooks/use-loop-down'
import { startOfDay } from '@/lib/digest'
import { renderRouted } from '@/test-utils'

import { AllClear, EmptyAttention } from './all-clear'

afterEach(cleanup)

const TICK: Tick = {
    id: 812,
    started_at: '2026-10-08T11:58:00Z',
    ended_at: '2026-10-08T12:00:00Z',
    status: 'ok',
    dry_run: false,
    summary: null,
    decisions: 0,
    cost_usd: null,
    new_tokens: null,
    woken_by: null,
} as Tick

interface Seed {
    /** The journal's count of today; undefined leaves it unread. */
    today?: RunsSince
    /** The runs the stream sent. */
    runs?: Run[]
    /** The latest tick. */
    tick?: Tick | null
    /** The loop's pause. */
    paused?: Pause | null
}

// A client with nothing to fetch: every read is what the test seeds.
function seeded({ today, runs = [], tick = null, paused = null }: Seed = {}) {
    const client = new QueryClient()
    for (const queryKey of [keys.tickets, keys.tick, keys.loop, keys.runs, keys.reviews, keys.chores, keys.tasks]) {
        client.setQueryDefaults(queryKey, { enabled: false })
    }
    client.setQueryDefaults(['runs-since'], { enabled: false })
    client.setQueryData(keys.tick, { tick, acknowledged: null })
    client.setQueryData(keys.loop, { paused })
    client.setQueryData(keys.runs, runs)
    client.setQueryData(keys.reviews, [])
    client.setQueryData(keys.chores, [])
    client.setQueryData(keys.tasks, [])
    if (today !== undefined) {
        client.setQueryData(keys.runsSince(startOfDay(Date.now())), today)
    }
    return client
}

describe('AllClear', () => {
    it('says nothing needs the operator while the loop answers', async () => {
        await renderRouted(<AllClear />, { client: seeded() })
        expect(screen.getByTestId('all-clear').textContent).toContain('Nothing needs you.')
        expect(screen.getByTestId('all-clear').textContent).toContain('all clear under the canopy')
    })

    it("says nothing needed them as of the drop, and never celebrates, while the loop isn't answering", async () => {
        await renderRouted(
            <StreamContext value={{ status: 'reconnecting', downSince: Date.now() - 60_000 }}>
                <AllClear />
            </StreamContext>,
            { client: seeded({ today: { prs_opened: 2, ended: 5 }, tick: TICK, runs: mockRuns }) },
        )
        await waitFor(() => {
            expect(screen.getByTestId('all-clear').textContent).toMatch(/^Nothing needed you as of .+\./u)
        })
        const said = screen.getByTestId('all-clear').textContent
        expect(said).not.toContain('all clear')
        // What the digest would say is only what the loop last said: none of it stands beside the timestamp.
        expect(said).not.toContain('Today')
        expect(said).not.toContain('Working now')
        expect(said).not.toContain('Last tick')
    })

    it('says what the journal holds of today', async () => {
        await renderRouted(<AllClear />, { client: seeded({ today: { prs_opened: 2, ended: 5 } }) })
        expect(screen.getByTestId('all-clear-today').textContent).toBe('Today: 2 PRs opened · 5 runs ended')
    })

    it('drops the line of the day when the day held nothing', async () => {
        await renderRouted(<AllClear />, { client: seeded({ today: { prs_opened: 0, ended: 0 } }) })
        expect(screen.queryByTestId('all-clear-today')).toBeNull()
    })

    it('counts what works as the rail does, and links to Workspace', async () => {
        const working = mockRuns.filter((run) => run.state === 'running' || run.state === 'blocked')
        expect(working.length).toBeGreaterThan(0)
        const { router } = await renderRouted(<AllClear />, { client: seeded({ runs: working }) })
        const link = screen.getByTestId('all-clear-working')
        expect(link.textContent).toMatch(/^Working now: \d+$/u)
        await act(async () => {
            fireEvent.click(link)
            await Promise.resolve()
        })
        expect(router.state.location.pathname).toBe('/workspace')
    })

    it('says nothing of the work when none works', async () => {
        await renderRouted(<AllClear />, { client: seeded() })
        expect(screen.queryByTestId('all-clear-working')).toBeNull()
    })

    it('names the latest tick, its status too when it did not end ok', async () => {
        await renderRouted(<AllClear />, { client: seeded({ tick: TICK }) })
        expect(screen.getByTestId('all-clear-tick').textContent).toMatch(/^Last tick \S+ ago$/u)
        cleanup()

        await renderRouted(<AllClear />, { client: seeded({ tick: { ...TICK, status: 'overseer_failed' } }) })
        expect(screen.getByTestId('all-clear-tick').textContent).toMatch(/^Last tick overseer failed \S+ ago$/u)
    })

    it('says a dry run for what it is', async () => {
        await renderRouted(<AllClear />, { client: seeded({ tick: { ...TICK, dry_run: true } }) })
        expect(screen.getByTestId('all-clear-tick').textContent).toMatch(/^Last dry run \S+ ago$/u)
    })

    it('says a tick is running while one is', async () => {
        await renderRouted(<AllClear />, {
            client: seeded({ tick: { ...TICK, status: 'running', ended_at: null } }),
        })
        expect(screen.getByTestId('all-clear-tick').textContent).toMatch(/^Tick running for \S+$/u)
    })

    it('names no tick before the first', async () => {
        await renderRouted(<AllClear />, { client: seeded({ tick: null }) })
        expect(screen.queryByTestId('all-clear-tick')).toBeNull()
    })

    it('says the loop is paused, so a quiet page is not read as a quiet loop', async () => {
        const paused = { since: '2026-10-08T11:00:00Z', channel: 'web' } as Pause
        await renderRouted(<AllClear />, { client: seeded({ paused, tick: TICK }) })
        const line = screen.getByTestId('all-clear-paused')
        expect(line.textContent).toMatch(/^Paused \S+ ago: no tick starts until you resume\.$/u)
        expect(within(screen.getByTestId('all-clear')).getByText('Nothing needs you.')).toBeDefined()
    })
})

function renderEmpty(tickets: TicketSummary[] | undefined, { failed = false }: { failed?: boolean } = {}) {
    const client = seeded()
    if (tickets !== undefined) {
        client.setQueryData(keys.tickets, tickets)
    }
    if (failed) {
        client
            .getQueryCache()
            .build(client, { queryKey: keys.tickets })
            .setState({
                status: 'error',
                error: new Error('the loop is down'),
            })
    }
    return renderRouted(<EmptyAttention />, { client })
}

describe('EmptyAttention', () => {
    it('names the first step, not all clear, while the journal holds no ticket', async () => {
        const { router } = await renderEmpty([])
        expect(screen.getByTestId('first-run').textContent).toBe(
            'no tickets yet: give one your queue label in the tracker, or start one privately on Tickets, ' +
                'then Tick now, and what needs you lands here',
        )
        expect(screen.queryByTestId('all-clear')).toBeNull()
        expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Tick now' }).disabled).toBe(false)

        await act(async () => {
            fireEvent.click(screen.getByRole('link', { name: 'Tickets' }))
            await Promise.resolve()
        })
        expect(router.state.location.pathname).toBe('/tickets')
    })

    it('is all clear once there was work and none of it is listed', async () => {
        await renderEmpty(mockTickets)
        expect(screen.getByTestId('all-clear').textContent).toContain('Nothing needs you.')
        expect(screen.queryByTestId('first-run')).toBeNull()
    })

    it('says neither until the tickets are read', async () => {
        await renderEmpty(undefined)
        expect(screen.getByTestId('panel-skeleton')).toBeDefined()
        expect(screen.queryByTestId('all-clear')).toBeNull()
        expect(screen.queryByTestId('first-run')).toBeNull()
    })

    it('is all clear, as before, when the tickets read failed', async () => {
        await renderEmpty(undefined, { failed: true })
        expect(screen.getByTestId('all-clear').textContent).toContain('Nothing needs you.')
        expect(screen.queryByTestId('panel-skeleton')).toBeNull()
        expect(screen.queryByTestId('first-run')).toBeNull()
    })
})
