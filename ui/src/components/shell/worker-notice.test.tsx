import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { mockCapacity } from '@/api/mocks'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { keys } from '@/api/queries'
import type { LoopState } from '@/api/types'
import { DEFAULT_CLOCK } from '@/lib/clock'
import { localTime } from '@/lib/time'

import { NoticeBanner } from './worker-notice'

const QUIET: LoopState = { capacity: mockCapacity, memory: null, notice: null, paused: null }
const TOLD: LoopState = {
    ...QUIET,
    notice: {
        channel: 'cli',
        text: 'Freeze on main until the release: see https://example.com/freeze',
        since: '2026-10-08T11:00:00Z',
        lapses_at: '2026-10-08T15:00:00Z',
    },
}

// Every request the banner sends, and what the server stand-in answers each.
let sent: string[] = []
let answer: Response | undefined

const server: Middleware = {
    onRequest({ request }) {
        sent.push(`${request.method} ${new URL(request.url).pathname}`)
        return answer
    },
}

beforeEach(() => {
    sent = []
    answer = undefined
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

function renderBanner(loop: LoopState | undefined) {
    const client = new QueryClient()
    // Nothing is fetched: the loop's state is what the test seeds, as the stream would send it.
    client.setQueryDefaults(keys.loop, { enabled: false })
    if (loop !== undefined) {
        client.setQueryData(keys.loop, loop)
    }
    render(
        <QueryClientProvider client={client}>
            <NoticeBanner />
        </QueryClientProvider>,
    )
}

describe('NoticeBanner', () => {
    it.each([
        ['no notice is in force', QUIET],
        ['the loop state has not arrived', undefined],
    ] as const)('shows nothing when %s', (_, loop) => {
        renderBanner(loop)
        expect(screen.queryByRole('region', { name: 'Notice to workers' })).toBeNull()
    })

    it('says what workers are told, its link followable, until when runs hear it, and where it was set', () => {
        renderBanner(TOLD)
        const banner = screen.getByRole('region', { name: 'Notice to workers' })
        expect(banner.textContent).toContain('Notice to workers: Freeze on main until the release')
        expect(screen.getByRole('link', { name: 'https://example.com/freeze' })).toBeDefined()
        const until = screen.getByText(
            `Every run dispatched until ${localTime('2026-10-08T15:00:00Z', DEFAULT_CLOCK)} hears it.`,
        )
        expect(until.title).toBe(`Set at ${localTime('2026-10-08T11:00:00Z', DEFAULT_CLOCK)} from \`canopy notice\``)
    })

    it('clears the notice as `canopy notice --clear` does, and goes once none is in force', async () => {
        answer = Response.json({ already: false, loop: QUIET })
        renderBanner(TOLD)

        fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
        await waitFor(() => {
            expect(screen.queryByRole('region', { name: 'Notice to workers' })).toBeNull()
        })
        expect(sent).toEqual(['POST /api/loop/notice/clear'])
    })

    it('keeps the notice and names the guard when the server refuses to clear it', async () => {
        answer = Response.json({ detail: { guard: 'journal_locked', reason: 'the journal is busy' } }, { status: 409 })
        renderBanner(TOLD)

        fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
        expect((await screen.findByRole('alert')).textContent).toBe('refused (journal_locked): the journal is busy')
        expect(screen.getByRole('region', { name: 'Notice to workers' })).toBeDefined()
    })
})
