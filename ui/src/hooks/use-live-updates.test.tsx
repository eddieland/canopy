import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { mockAttention, mockReviews, mockTickets } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { TicketSummary } from '@/api/types'
import { ToastContext } from '@/hooks/use-toast'
import { DEFAULTS, setToastSettings } from '@/lib/toast-settings'
import type { NewToast } from '@/lib/toasts'
import { FakeEventSource } from '@/test-utils'

import { useLiveUpdates } from './use-live-updates'

beforeEach(() => {
    FakeEventSource.instances = []
    vi.stubGlobal('EventSource', FakeEventSource)
    vi.useFakeTimers()
})

afterEach(() => {
    cleanup()
    vi.useRealTimers()
    setToastSettings(DEFAULTS)
})

function live(
    client: QueryClient,
    enabled = true,
    show: (toast: NewToast) => void = vi.fn<(toast: NewToast) => void>(),
) {
    const wrapper = ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>
            <ToastContext value={show}>{children}</ToastContext>
        </QueryClientProvider>
    )
    return renderHook(() => useLiveUpdates(enabled), { wrapper })
}

// The mock tickets, each in `phase`.
function inPhase(phase: string): TicketSummary[] {
    return mockTickets.map((ticket) => Object.assign(structuredClone(ticket), { phase }))
}

function latest(): FakeEventSource {
    const source = FakeEventSource.instances.at(-1)
    if (!source) {
        throw new Error('no EventSource was created')
    }
    return source
}

describe('useLiveUpdates', () => {
    it("opens the API's stream only when enabled, as when signed in", () => {
        live(new QueryClient(), false)
        expect(FakeEventSource.instances).toEqual([])

        live(new QueryClient())
        expect(latest().url).toBe('/api/events')
    })

    it('writes what the stream sends into the cache, and drops what it cannot read', () => {
        const client = new QueryClient()
        live(client)
        act(() => {
            latest().open()
            latest().send(JSON.stringify({ type: 'tickets.updated', tickets: mockTickets }))
            latest().send('{"type":"tickets.updated","tickets":null}')
        })
        expect(client.getQueryData(keys.tickets)).toEqual(mockTickets)
    })

    it('shows a toast for a ticket moving into a state Settings turned on, and none for the first list', () => {
        const show = vi.fn<(toast: NewToast) => void>()
        setToastSettings({ tickets: ['blocked'], reviews: [] })
        live(new QueryClient(), true, show)
        act(() => {
            latest().open()
            latest().send(JSON.stringify({ type: 'tickets.updated', tickets: inPhase('running') }))
        })
        expect(show).not.toHaveBeenCalled()

        act(() => {
            latest().send(JSON.stringify({ type: 'tickets.updated', tickets: inPhase('ready') }))
            latest().send(JSON.stringify({ type: 'tickets.updated', tickets: inPhase('blocked') }))
        })
        expect(show.mock.calls).toEqual([
            [{ title: 'ABC-102: blocked', detail: 'Export reports as CSV', tone: 'moved' }],
        ])
    })

    it('shows a toast for a review that ended in a state Settings turned on', () => {
        const show = vi.fn<(toast: NewToast) => void>()
        setToastSettings({ tickets: [], reviews: ['clean'] })
        live(new QueryClient(), true, show)
        const ended = mockReviews.map((review) =>
            Object.assign(structuredClone(review), { state: 'done', verdict: 'clean' }),
        )
        act(() => {
            latest().open()
            latest().send(JSON.stringify({ type: 'reviews.updated', reviews: mockReviews }))
            latest().send(JSON.stringify({ type: 'reviews.updated', reviews: ended }))
        })
        expect(show.mock.calls).toEqual([[{ title: 'review:4: clean', detail: 'acme/web#12', tone: 'moved' }]])
    })

    it("after a drop, reads the server's meta and the tickets shown again, not the lists the stream resends", () => {
        const client = new QueryClient()
        client.setQueryData(keys.meta, {})
        client.setQueryData(keys.ticket('ABC-1'), {})
        client.setQueryData(keys.attention, mockAttention)
        live(client)
        act(() => latest().open())
        expect(client.getQueryState(keys.meta)?.isInvalidated).toBe(false)

        act(() => {
            latest().drop()
            latest().open()
        })
        expect(client.getQueryState(keys.meta)?.isInvalidated).toBe(true)
        expect(client.getQueryState(keys.ticket('ABC-1'))?.isInvalidated).toBe(true)
        expect(client.getQueryState(keys.attention)?.isInvalidated).toBe(false)
    })
})
