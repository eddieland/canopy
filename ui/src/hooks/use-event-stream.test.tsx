import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { FakeEventSource } from '@/test-utils'

import { HIDDEN_MS, RETRY_FIRST_MS, useEventStream } from './use-event-stream'

let visibility: DocumentVisibilityState = 'visible'

beforeEach(() => {
    FakeEventSource.instances = []
    vi.stubGlobal('EventSource', FakeEventSource)
    visibility = 'visible'
    vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility)
    vi.useFakeTimers()
})

afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.restoreAllMocks()
})

function show(state: DocumentVisibilityState): void {
    visibility = state
    document.dispatchEvent(new Event('visibilitychange'))
}

function stream(onReconnect = vi.fn<() => void>()) {
    const hook = renderHook(() => useEventStream('/api/events', { parse: (d) => d, onEvent: () => {}, onReconnect }))
    act(() => latest().open())
    return { ...hook, onReconnect }
}

function latest(): FakeEventSource {
    const source = FakeEventSource.instances.at(-1)
    if (!source) {
        throw new Error('no EventSource was created')
    }
    return source
}

describe('useEventStream', () => {
    it('reports its status, parses messages, and asks for a catch-up after a drop', () => {
        const onEvent = vi.fn<(event: string) => void>()
        const onReconnect = vi.fn<() => void>()
        const { result, unmount } = renderHook(() =>
            useEventStream('/api/events', {
                parse: (d) => (d === 'skip' ? null : d.toUpperCase()),
                onEvent,
                onReconnect,
            }),
        )
        expect(result.current.status).toBe('connecting')

        act(() => latest().open())
        expect(result.current.status).toBe('open')

        act(() => {
            latest().send('a')
            latest().send('skip')
        })
        expect(onEvent).toHaveBeenCalledExactlyOnceWith('A')

        act(() => latest().drop())
        expect(result.current.status).toBe('reconnecting')
        act(() => latest().open())
        expect(result.current.status).toBe('open')
        expect(onReconnect).toHaveBeenCalledOnce()

        unmount()
        expect(latest().closed).toBe(true)
    })

    it('opens nothing when disabled', () => {
        const { result } = renderHook(() =>
            useEventStream('/api/events', { parse: (d) => d, onEvent: () => {}, enabled: false }),
        )
        expect(result.current.status).toBe('closed')
        expect(FakeEventSource.instances).toHaveLength(0)
    })

    it('starts over when a dropped stream has not come back, waiting longer each time', () => {
        const { result, onReconnect } = stream()
        const first = latest()
        act(() => first.drop())
        act(() => first.drop())
        act(() => {
            vi.advanceTimersByTime(RETRY_FIRST_MS - 1)
        })
        expect(FakeEventSource.instances).toHaveLength(1)

        act(() => {
            vi.advanceTimersByTime(1)
        })
        expect(first.closed).toBe(true)
        expect(FakeEventSource.instances).toHaveLength(2)
        expect(result.current.status).toBe('reconnecting')

        act(() => latest().drop())
        act(() => {
            vi.advanceTimersByTime(RETRY_FIRST_MS)
        })
        expect(FakeEventSource.instances).toHaveLength(2)
        act(() => {
            vi.advanceTimersByTime(RETRY_FIRST_MS)
        })
        expect(FakeEventSource.instances).toHaveLength(3)

        act(() => latest().open())
        expect(result.current.status).toBe('open')
        expect(onReconnect).toHaveBeenCalledOnce()
    })

    it('leaves a stream the browser brought back in time alone', () => {
        const { result, onReconnect } = stream()
        act(() => latest().drop())
        act(() => latest().open())
        act(() => {
            vi.advanceTimersByTime(RETRY_FIRST_MS * 4)
        })
        expect(FakeEventSource.instances).toHaveLength(1)
        expect(result.current.status).toBe('open')
        expect(onReconnect).toHaveBeenCalledOnce()
    })

    it('tries again after the server refused it, which the browser never does', () => {
        const { result } = stream()
        act(() => latest().refuse())
        expect(result.current.status).toBe('reconnecting')
        act(() => {
            vi.advanceTimersByTime(RETRY_FIRST_MS)
        })
        expect(FakeEventSource.instances).toHaveLength(2)
        act(() => latest().open())
        expect(result.current.status).toBe('open')
    })

    it('starts over when the page is shown after long enough hidden to have lost the stream unawares', () => {
        const { result, onReconnect } = stream()
        act(() => show('hidden'))
        act(() => {
            vi.advanceTimersByTime(HIDDEN_MS - 1)
        })
        act(() => show('visible'))
        expect(FakeEventSource.instances).toHaveLength(1)

        act(() => show('hidden'))
        act(() => {
            vi.advanceTimersByTime(HIDDEN_MS)
        })
        act(() => show('visible'))
        expect(FakeEventSource.instances).toHaveLength(2)
        expect(FakeEventSource.instances[0]?.closed).toBe(true)
        expect(result.current.status).toBe('reconnecting')
        act(() => latest().open())
        expect(onReconnect).toHaveBeenCalledOnce()
    })

    it('starts over at once when the page is shown or the device is online with the stream down', () => {
        stream()
        act(() => latest().drop())
        act(() => show('hidden'))
        act(() => show('visible'))
        expect(FakeEventSource.instances).toHaveLength(2)

        act(() => latest().drop())
        act(() => {
            globalThis.dispatchEvent(new Event('online'))
        })
        expect(FakeEventSource.instances).toHaveLength(3)
        act(() => latest().open())
        act(() => {
            globalThis.dispatchEvent(new Event('online'))
        })
        expect(FakeEventSource.instances).toHaveLength(3)
    })

    it('says since when a stream that never reopens has been down, the first drop, through every retry', () => {
        const { result } = stream()
        expect(result.current.downSince).toBeNull()
        const dropped = Date.now()
        act(() => latest().drop())
        expect(result.current).toEqual({ status: 'reconnecting', downSince: dropped })
        for (let n = 0; n < 6; n += 1) {
            act(() => {
                vi.advanceTimersByTime(60_000)
            })
            act(() => latest().refuse())
        }
        expect(FakeEventSource.instances.length).toBeGreaterThan(4)
        expect(result.current).toEqual({ status: 'reconnecting', downSince: dropped })

        act(() => latest().open())
        expect(result.current).toEqual({ status: 'open', downSince: null })
        act(() => latest().drop())
        expect(result.current.downSince).toBe(Date.now())
    })

    it('stops trying once unmounted', () => {
        const { unmount } = stream()
        act(() => latest().drop())
        unmount()
        act(() => {
            vi.advanceTimersByTime(RETRY_FIRST_MS * 10)
        })
        act(() => {
            globalThis.dispatchEvent(new Event('online'))
        })
        expect(FakeEventSource.instances).toHaveLength(1)
        expect(latest().closed).toBe(true)
    })
})
