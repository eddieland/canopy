import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useEventStream } from './use-event-stream'

/** Stands in for EventSource: records instances, and lets a test play the server. */
class FakeEventSource extends EventTarget {
    static readonly CONNECTING = 0
    static readonly OPEN = 1
    static readonly CLOSED = 2
    static instances: FakeEventSource[] = []
    readyState = FakeEventSource.CONNECTING
    closed = false
    readonly url: string

    constructor(url: string) {
        super()
        this.url = url
        FakeEventSource.instances.push(this)
    }

    open(): void {
        this.readyState = FakeEventSource.OPEN
        this.dispatchEvent(new Event('open'))
    }

    send(data: string): void {
        this.dispatchEvent(new MessageEvent('message', { data }))
    }

    drop(): void {
        this.readyState = FakeEventSource.CONNECTING
        this.dispatchEvent(new Event('error'))
    }

    close(): void {
        this.closed = true
        this.readyState = FakeEventSource.CLOSED
    }
}

beforeEach(() => {
    FakeEventSource.instances = []
    vi.stubGlobal('EventSource', FakeEventSource)
})

function latest(): FakeEventSource {
    const source = FakeEventSource.instances.at(-1)
    if (!source) throw new Error('no EventSource was created')
    return source
}

describe('useEventStream', () => {
    it('reports its status, parses messages, and asks for a catch-up after a drop', () => {
        const onEvent = vi.fn()
        const onReconnect = vi.fn()
        const { result, unmount } = renderHook(() =>
            useEventStream('/api/events', {
                parse: (d) => (d === 'skip' ? null : d.toUpperCase()),
                onEvent,
                onReconnect,
            }),
        )
        expect(result.current).toBe('connecting')

        act(() => latest().open())
        expect(result.current).toBe('open')

        act(() => {
            latest().send('a')
            latest().send('skip')
        })
        expect(onEvent).toHaveBeenCalledExactlyOnceWith('A')

        act(() => latest().drop())
        expect(result.current).toBe('reconnecting')
        act(() => latest().open())
        expect(result.current).toBe('open')
        expect(onReconnect).toHaveBeenCalledOnce()

        unmount()
        expect(latest().closed).toBe(true)
    })

    it('opens nothing when disabled', () => {
        const { result } = renderHook(() =>
            useEventStream('/api/events', { parse: (d) => d, onEvent: () => {}, enabled: false }),
        )
        expect(result.current).toBe('closed')
        expect(FakeEventSource.instances).toHaveLength(0)
    })
})
