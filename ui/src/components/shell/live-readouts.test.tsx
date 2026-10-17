import { QueryClient } from '@tanstack/react-query'
import { act, cleanup, fireEvent, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { keys } from '@/api/queries'
import type { LoopState, MemoryState, Meta, Tick } from '@/api/types'
import type { StreamStatus } from '@/hooks/use-event-stream'
import { renderRouted } from '@/test-utils'

import { LiveReadouts } from './live-readouts'

const META: Meta = {
    branch_urls: {},
    build: null,
    mock: false,
    ticket_url: null,
    version: '0.4.0',
    workspace_root: '/w',
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
    { meta = META, tick = null, memory = null }: { meta?: Meta; tick?: Tick | null; memory?: MemoryState | null } = {},
) {
    const client = new QueryClient()
    // Nothing is fetched: each readout's data is what the test seeds, as the stream would send it.
    for (const key of [keys.meta, keys.tick, keys.loop]) {
        client.setQueryDefaults(key, { enabled: false })
    }
    client.setQueryData(keys.meta, meta)
    client.setQueryData(keys.tick, { tick, acknowledged: null })
    client.setQueryData<LoopState>(keys.loop, { memory, notice: null, paused: null })
    return renderRouted(<LiveReadouts stream={stream} />, { client })
}

describe('LiveReadouts', () => {
    it.each([
        ['connecting', 'connecting'],
        ['open', 'live'],
        ['reconnecting', 'reconnecting'],
        ['closed', 'offline'],
    ] as const)('says a %s stream is %s', async (stream, said) => {
        await renderReadouts(stream)
        expect(screen.getByText(said)).toBeDefined()
    })

    it('flags fixture data as mock, and only fixture data', async () => {
        const { unmount } = await renderReadouts('open', { meta: { ...META, mock: true } })
        expect(screen.getByText('mock')).toBeDefined()
        unmount()

        await renderReadouts('open')
        expect(screen.queryByText('mock')).toBeNull()
    })

    it('shows no tick before the first, and no memory while no tier is on', async () => {
        await renderReadouts('open')
        expect(screen.queryByRole('link')).toBeNull()
    })

    it("names the latest tick as `canopy status` does, its summary on hover, and opens the tick's page", async () => {
        const { router } = await renderReadouts('open', { tick: TICK })
        expect(screen.getByTitle(TICK.summary ?? '').textContent).toBe('tick:12 · 3m ago')

        await act(async () => {
            fireEvent.click(screen.getByRole('link', { name: 'tick:12' }))
            await Promise.resolve()
        })
        expect(router.state.location.pathname).toBe('/ticks/12')
    })

    it.each([
        ['a dry run', { dry_run: true }, 'tick:12 (dry run) · 3m ago'],
        ['a tick that failed, in its own word', { status: 'overseer_failed' }, 'tick:12 overseer failed · 3m ago'],
        ['a tick still running, for how long', { status: 'running', ended_at: null }, 'tick:12 running · for 4m'],
    ] as const)('says so for %s', async (_, change, said) => {
        await renderReadouts('open', { tick: { ...TICK, ...change } })
        expect(screen.getByTitle(TICK.summary ?? '').textContent).toBe(said)
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
})
