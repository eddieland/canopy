import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { mockCapacity } from '@/api/mocks'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { keys } from '@/api/queries'
import type { LoopState, WorkerNotice } from '@/api/types'
import { DEFAULT_CLOCK } from '@/lib/clock'
import { localTime } from '@/lib/time'

import { NoticeBanner } from './worker-notice'

const QUIET: LoopState = { capacity: mockCapacity, memory: null, notice: null, paused: null }
const FREEZE: WorkerNotice = {
    channel: 'cli',
    text: 'Freeze on main until the release: see https://example.com/freeze',
    since: '2026-10-08T11:00:00Z',
    lapses_at: '2026-10-08T15:00:00Z',
}
const TOLD: LoopState = { ...QUIET, notice: FREEZE }

// Every request the banner sends, the body of each that has one, and what the server stand-in answers each.
let sent: string[] = []
let bodies: unknown[] = []
let answer: Response | undefined

const server: Middleware = {
    async onRequest({ request }) {
        sent.push(`${request.method} ${new URL(request.url).pathname}`)
        const body = await request.clone().text()
        if (body !== '') {
            bodies.push(JSON.parse(body))
        }
        return answer
    },
}

beforeEach(() => {
    sent = []
    bodies = []
    answer = undefined
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

function renderBanner(loop: LoopState | undefined): QueryClient {
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
    return client
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

    it('renews the notice with its words, for as long as it was set for, as `canopy notice --for` does', async () => {
        const renewed = { ...FREEZE, since: '2026-10-08T12:00:00Z', lapses_at: '2026-10-08T16:00:00Z' }
        answer = Response.json({ already: false, loop: { ...TOLD, notice: renewed } })
        renderBanner(TOLD)

        const button = screen.getByRole('button', { name: 'Renew' })
        expect(button.title).toBe('Renew the notice for 4h, as long as it was set for, from now.')
        fireEvent.click(button)
        await screen.findByText(
            `Every run dispatched until ${localTime('2026-10-08T16:00:00Z', DEFAULT_CLOCK)} hears it.`,
        )
        expect(sent).toEqual(['POST /api/loop/notice'])
        expect(bodies).toEqual([{ text: FREEZE.text, minutes: 240 }])
    })

    it('edits the words in place, keeping the time it lapses, and shows the notice it set', async () => {
        vi.useFakeTimers({ now: Date.parse('2026-10-08T12:00:00Z'), toFake: ['Date'] })
        try {
            const edited = { ...FREEZE, text: 'Freeze lifted at noon.', since: '2026-10-08T12:00:00Z' }
            answer = Response.json({ already: false, loop: { ...TOLD, notice: edited } })
            renderBanner(TOLD)

            fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
            const field = screen.getByRole<HTMLTextAreaElement>('textbox', { name: "The notice's words" })
            expect(field.value).toBe(FREEZE.text)
            const save = screen.getByRole<HTMLButtonElement>('button', { name: /^Save notice/u })
            // Saving the same words for the same time would change nothing.
            expect(save.disabled).toBe(true)
            fireEvent.change(field, { target: { value: 'Freeze lifted at noon.' } })
            fireEvent.click(save)

            await screen.findByText('Freeze lifted at noon.')
            expect(screen.queryByRole('textbox')).toBeNull()
            // Three hours left of the four it was set for.
            expect(bodies).toEqual([{ text: 'Freeze lifted at noon.', minutes: 180 }])
        } finally {
            vi.useRealTimers()
        }
    })

    it('sets the edited notice for the time picked in place of the one it had', async () => {
        answer = Response.json({ already: false, loop: TOLD })
        renderBanner(TOLD)

        fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
        fireEvent.click(screen.getByRole('radio', { name: '1 day' }))
        fireEvent.click(screen.getByRole('button', { name: /^Save notice/u }))
        await waitFor(() => {
            expect(screen.queryByRole('textbox')).toBeNull()
        })
        expect(bodies).toEqual([{ text: FREEZE.text, minutes: 1440 }])
    })

    it('drops an edit on Cancel and sends nothing', () => {
        renderBanner(TOLD)

        fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
        fireEvent.change(screen.getByRole('textbox'), { target: { value: 'never mind' } })
        fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
        expect(screen.queryByRole('textbox')).toBeNull()
        expect(screen.getByRole('region', { name: 'Notice to workers' }).textContent).toContain('Freeze on main')
        expect(sent).toEqual([])
    })

    it.each([
        ['lapses or is cleared', [QUIET, { ...QUIET, notice: { ...FREEZE, since: '2026-10-08T13:00:00Z' } }]],
        ['is replaced from elsewhere', [{ ...QUIET, notice: { ...FREEZE, since: '2026-10-08T13:00:00Z' } }]],
    ] as const)('ends an open edit when the notice %s, so the next one shows as told', async (_, states) => {
        const client = renderBanner(TOLD)

        fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
        expect(screen.getByRole('textbox')).toBeDefined()
        for (const state of states) {
            act(() => {
                client.setQueryData(keys.loop, state)
            })
        }
        await screen.findByRole('button', { name: 'Edit' })
        expect(screen.queryByRole('textbox')).toBeNull()
        expect(screen.getByRole('button', { name: 'Renew' })).toBeDefined()
    })

    it('keeps the edit open and names the guard when the server refuses it', async () => {
        answer = Response.json({ detail: { guard: 'too_long', reason: 'the notice is 1100 bytes' } }, { status: 409 })
        renderBanner(TOLD)

        fireEvent.click(screen.getByRole('button', { name: 'Edit' }))
        fireEvent.change(screen.getByRole('textbox'), { target: { value: 'x'.repeat(1100) } })
        fireEvent.click(screen.getByRole('button', { name: /^Save notice/u }))
        expect((await screen.findByRole('alert')).textContent).toBe('refused (too_long): the notice is 1100 bytes')
        expect(screen.getByRole('textbox')).toBeDefined()
    })

    it('keeps the notice and names the guard when the server refuses to clear it', async () => {
        answer = Response.json({ detail: { guard: 'journal_locked', reason: 'the journal is busy' } }, { status: 409 })
        renderBanner(TOLD)

        fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
        expect((await screen.findByRole('alert')).textContent).toBe('refused (journal_locked): the journal is busy')
        expect(screen.getByRole('region', { name: 'Notice to workers' })).toBeDefined()
    })
})
