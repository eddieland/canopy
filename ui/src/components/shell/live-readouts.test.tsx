import { QueryClient } from '@tanstack/react-query'
import { act, cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { keys } from '@/api/queries'
import { mockCapacity } from '@/api/mocks'
import type { LoopState, MemoryState, Meta, Spend, SpendMonth, Tick } from '@/api/types'
import type { StreamStatus } from '@/hooks/use-event-stream'
import { StreamContext } from '@/hooks/use-loop-down'
import { renderRouted } from '@/test-utils'

import { LiveReadouts, StreamReadout } from './live-readouts'

const META: Meta = {
    branch_urls: {},
    build: null,
    mock: false,
    ticket_url: null,
    version: '0.4.0',
    workspace_root: '/w',
    repos: ['repo'],
}

const TICK: Tick = {
    id: 12,
    status: 'ok',
    dry_run: false,
    started_at: '2026-10-08T11:56:00Z',
    ended_at: '2026-10-08T11:57:00Z',
    summary: 'Dispatched ABC-101; waiting on ABC-102.',
    cost_usd: 0.12,
    decisions: 2,
    idle: false,
    new_tokens: 1200,
    peak_context: 9000,
    session_id: 'ses_tick12',
    woken_by: null,
    canopy_version: null,
    activity: null,
}

const TIER: MemoryState['lessons'] = {
    band: 'Recording only. Nothing reads it yet.',
    mode: 'record',
    words: 'recording',
}
const MEMORY: MemoryState = {
    readout: 'memory: recording',
    tiers: 'lessons: record, ticket notes: record',
    lessons: TIER,
    ticket_notes: TIER,
    proposals_waiting: 0,
}

// October 2026 a quarter gone, with a $40 budget: $15.76 spent, on pace for $63.04, over it.
const MONTH: SpendMonth = {
    month: '2026-10',
    since: '2026-10-01T00:00:00Z',
    until: '2026-11-01T00:00:00Z',
    budget_usd: 40,
    spent_usd: 15.76,
    elapsed: 0.25,
    projected_usd: 63.04,
    alerts: [100],
    runs_usd: 15.76,
    outside_usd: 0,
    sessions_read_at: null,
}

// What the last day and 30 days cost, and the month against its budget, or none set.
function spendWith(budget: SpendMonth | null): Spend {
    const window = { since: '2026-10-07T12:00:00Z', hours: 24, cost_usd: 15.76 }
    return { day: window, month: { ...window, hours: 720 }, total_usd: 15.76, sessions_read_at: null, budget }
}

beforeEach(() => {
    // The ages read the clock: hold it three minutes after the tick ended.
    vi.useFakeTimers({ toFake: ['Date'], now: new Date('2026-10-08T12:00:00Z') })
})

afterEach(() => {
    cleanup()
    vi.useRealTimers()
})

function renderReadouts(
    stream: StreamStatus,
    {
        meta = META,
        tick = null,
        memory = null,
        budget = null,
        downSince = null,
        client = new QueryClient(),
    }: {
        meta?: Meta
        tick?: Tick | null
        memory?: MemoryState | null
        budget?: SpendMonth | null
        downSince?: number | null
        client?: QueryClient
    } = {},
) {
    // Nothing is fetched: each readout's data is what the test seeds, as the stream would send it.
    for (const key of [keys.meta, keys.tick, keys.loop, keys.host, keys.spend]) {
        client.setQueryDefaults(key, { enabled: false })
    }
    client.setQueryData(keys.meta, meta)
    client.setQueryData(keys.tick, { tick, acknowledged: null })
    client.setQueryData(keys.spend, spendWith(budget))
    client.setQueryData<LoopState>(keys.loop, { capacity: mockCapacity, memory, notice: null, paused: null })
    return renderRouted(
        <StreamContext value={{ status: stream, downSince }}>
            <StreamReadout stream={stream} />
            <LiveReadouts />
        </StreamContext>,
        { client },
    )
}

describe('LiveReadouts', () => {
    it.each([
        ['connecting', 'opening'],
        ['open', 'live'],
        ['reconnecting', 'retrying'],
        ['closed', 'offline'],
    ] as const)('says a %s stream is %s', async (stream, said) => {
        await renderReadouts(stream)
        expect(screen.getByText(said)).toBeDefined()
    })

    it('says a stream just dropped is retrying, and once down past the first retry, for how long', async () => {
        const { unmount } = await renderReadouts('reconnecting', { downSince: Date.now() - 1_000 })
        expect(screen.getByTestId('stream-status').textContent).toBe('retrying')
        unmount()

        await renderReadouts('reconnecting', { downSince: Date.now() - 2 * 60_000 })
        await waitFor(() => {
            expect(screen.getByTestId('stream-status').textContent).toBe('down · 2m')
        })
        expect(screen.getByTestId('stream-status').title).toMatch(/^Down since .+: the loop isn't answering\.$/u)
    })

    it('flags fixture data as mock, and only fixture data', async () => {
        const { unmount } = await renderReadouts('open', { meta: { ...META, mock: true } })
        expect(screen.getByText('mock')).toBeDefined()
        unmount()

        await renderReadouts('open')
        expect(screen.queryByText('mock')).toBeNull()
    })

    it('says no tick yet before the first, and shows no memory while no tier is on', async () => {
        await renderReadouts('open')
        expect(screen.getByTestId('last-tick').textContent).toBe('no tick yet')
        expect(screen.queryByRole('link')).toBeNull()
    })

    it('says nothing of the tick until its read lands, then no tick yet until the first one runs', async () => {
        const client = new QueryClient()
        client.setQueryDefaults(keys.tick, { enabled: false })
        client.setQueryDefaults(keys.loop, { enabled: false })
        client.setQueryDefaults(keys.host, { enabled: false })
        client.setQueryDefaults(keys.spend, { enabled: false })
        await renderRouted(<LiveReadouts />, { client })
        expect(screen.queryByTestId('last-tick')).toBeNull()

        act(() => {
            client.setQueryData(keys.tick, { tick: null, acknowledged: null })
        })
        expect((await screen.findByTestId('last-tick')).textContent).toBe('no tick yet')

        // The stream sends the first tick as it starts: the readout becomes it.
        act(() => {
            client.setQueryData(keys.tick, { tick: { ...TICK, status: 'running', ended_at: null }, acknowledged: null })
        })
        await waitFor(() => {
            expect(screen.getByTestId('last-tick').textContent).toBe('tick:12 running · for 4m')
        })
    })

    it('says the tick Tick now asked for is starting until its row lands, then shows it', async () => {
        const client = new QueryClient()
        for (const key of [keys.meta, keys.tick, keys.loop, keys.host, keys.spend]) {
            client.setQueryDefaults(key, { enabled: false })
        }
        client.setQueryData(keys.meta, META)
        client.setQueryData(keys.tick, { tick: TICK, acknowledged: null })
        await renderRouted(
            <StreamContext value={{ status: 'open', downSince: null }}>
                <LiveReadouts />
            </StreamContext>,
            { client },
        )
        expect(screen.getByTestId('last-tick').textContent).toBe('tick:12 · 3m ago')

        // Tick now's request, answered: the loop was asked, after tick 12.
        await act(async () => {
            await client
                .getMutationCache()
                .build(client, { mutationKey: keys.tickNow, mutationFn: () => Promise.resolve({ after_tick: false }) })
                .execute(12)
        })
        await waitFor(() => {
            expect(screen.getByTestId('last-tick').textContent).toBe('tick starting')
        })

        // The stream sends the tick asked for as it starts: the readout becomes it.
        act(() => {
            client.setQueryData(keys.tick, {
                tick: { ...TICK, id: 13, status: 'running', started_at: '2026-10-08T12:00:00Z', ended_at: null },
                acknowledged: null,
            })
        })
        await waitFor(() => {
            expect(screen.getByTestId('last-tick').textContent).toBe('tick:13 running · for 0s')
        })
    })

    it('says no tick is starting over the mock journal, where no loop runs to start one', async () => {
        const client = new QueryClient()
        await renderReadouts('open', { meta: { ...META, mock: true }, tick: TICK, client })
        await act(async () => {
            await client
                .getMutationCache()
                .build(client, { mutationKey: keys.tickNow, mutationFn: () => Promise.resolve({ after_tick: false }) })
                .execute(12)
            // Query batches what it tells the page into the next task: let that land before looking.
            await new Promise((resolve) => {
                setTimeout(resolve, 0)
            })
        })
        expect(screen.getByTestId('last-tick').textContent).toBe('tick:12 · 3m ago')
    })

    it("names the latest tick as `canopy status` does, and opens the tick's page", async () => {
        const { router } = await renderReadouts('open', { tick: TICK })
        expect(screen.getByTestId('last-tick').textContent).toBe('tick:12 · 3m ago')
        expect(screen.queryByText('no tick yet')).toBeNull()

        await act(async () => {
            fireEvent.click(screen.getByRole('link', { name: 'tick:12 · 3m ago' }))
            await Promise.resolve()
        })
        expect(router.state.location.pathname).toBe('/workspace/ticks/12')
    })

    it.each([
        ['a dry run', { dry_run: true }, 'tick:12 (dry run) · 3m ago'],
        ['a tick that failed, in its own word', { status: 'overseer_failed' }, 'tick:12 overseer failed · 3m ago'],
        ['a tick still running, for how long', { status: 'running', ended_at: null }, 'tick:12 running · for 4m'],
    ] as const)('says so for %s', async (_, change, said) => {
        await renderReadouts('open', { tick: { ...TICK, ...change } })
        expect(screen.getByTestId('last-tick').textContent).toBe(said)
    })

    it('shows the tick at a glance in a card when it has the focus', async () => {
        await renderReadouts('open', { tick: { ...TICK, woken_by: 'timer' } })
        act(() => {
            screen.getByTestId('last-tick').focus()
        })
        const card = await waitFor(() => screen.getByTestId('tick-card'))
        expect(card.textContent).toContain('Dispatched ABC-101; waiting on ABC-102.')
        expect(card.textContent).toContain(', took 1m')
        expect(card.textContent).toContain('2 decisions')
        expect(card.textContent).toContain('$0.12, 1.2k tokens')
        expect(card.textContent).toContain('timer')
    })

    it("keeps a failed tick's status as the CLI spells it on hover", async () => {
        await renderReadouts('open', { tick: { ...TICK, status: 'overseer_failed' } })
        expect(screen.getByText('overseer failed').title).toBe('overseer_failed')
    })

    it("says agent memory's mode in words, each tier's to a screen reader, and opens the memory page", async () => {
        const { router } = await renderReadouts('open', { memory: MEMORY })
        const link = screen.getByRole('link', { name: 'memory: recording: lessons: record, ticket notes: record' })
        expect(link.textContent).toBe('memory: recording')

        await act(async () => {
            fireEvent.click(link)
            await Promise.resolve()
        })
        expect(router.state.location.pathname).toBe('/memory')
    })

    it("shows each tier's mode and what reads it in a card, and the proposals waiting on you", async () => {
        await renderReadouts('open', { memory: { ...MEMORY, proposals_waiting: 2 } })
        act(() => {
            screen.getByTestId('memory-readout').focus()
        })
        const card = await waitFor(() => screen.getByTestId('memory-card'))
        expect(card.textContent).toContain('Recording only. Nothing reads it yet.')
        expect(card.textContent).toContain('2 proposals waiting on you')
    })

    it('shows the month against its budget in a card, with what the spend is made of', async () => {
        await renderReadouts('open', { budget: MONTH })
        act(() => {
            screen.getByTestId('budget-readout').focus()
        })
        const card = await waitFor(() => screen.getByTestId('budget-card'))
        expect(card.textContent).toContain('October 2026')
        expect(card.textContent).toContain('Headed over')
        expect(card.textContent).toContain('39%, $15.76 of $40')
        expect(card.textContent).toContain("$63.04 by the month's end")
        expect(card.textContent).toContain('25% gone by')
        expect(card.textContent).toContain("Canopy's runs $15.76.")
    })

    it('shows no budget while none is set', async () => {
        await renderReadouts('open')
        expect(screen.queryByTestId('budget-readout')).toBeNull()
    })

    it.each([
        ['on budget', { projected_usd: 31.52 }, 'under', '39%', 'On budget: $15.76 of $40 (39%), on pace for $31.52.'],
        ['headed over', {}, 'headed', '39%', 'Headed over: $15.76 of $40 (39%), on pace for $63.04.'],
        [
            'over budget',
            { spent_usd: 42.5, projected_usd: 170 },
            'over',
            '106%',
            'Over budget: $42.50 of $40 (106%), on pace for $170.00.',
        ],
    ] as const)('says the month is %s, in words, and opens the spend page', async (_, change, state, shown, said) => {
        const { router } = await renderReadouts('open', { budget: { ...MONTH, ...change } })
        const link = screen.getByRole('link', { name: said })
        expect(link.textContent).toBe(shown)
        expect(link.dataset['state']).toBe(state)

        await act(async () => {
            fireEvent.click(link)
            await Promise.resolve()
        })
        expect(router.state.location.pathname).toBe('/reports/spend')
    })
})
