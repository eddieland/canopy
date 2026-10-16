import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { mockAttention, mockTickets } from '@/api/mocks'
import { keys } from '@/api/queries'
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
})

function live(client: QueryClient, enabled = true) {
    const wrapper = ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    return renderHook(() => useLiveUpdates(enabled), { wrapper })
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
