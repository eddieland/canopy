import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import type { AnyRouter } from '@tanstack/react-router'
import { render } from '@testing-library/react'
import type { RenderResult } from '@testing-library/react'
import { createElement } from 'react'
import type { ReactNode } from 'react'
import { vi } from 'vitest'

/**
 * Renders `ui` as the one page of a router at `at`, so its links resolve, under a query client: `client`, or one with
 * nothing in it. Returns the render and the router, whose `state.location` says where a link took it.
 */
export async function renderRouted(
    ui: ReactNode,
    { at = '/', client = new QueryClient() }: { at?: string; client?: QueryClient } = {},
): Promise<RenderResult & { router: AnyRouter }> {
    const router = createRouter({
        routeTree: createRootRoute({ component: () => ui }),
        history: createMemoryHistory({ initialEntries: [at] }),
    })
    await router.load()
    const result = render(
        createElement(QueryClientProvider, { client }, createElement(RouterProvider, { router: router as AnyRouter })),
    )
    return { ...result, router }
}

/** Stubs matchMedia so `(prefers-color-scheme: dark)` matches when `dark`, and lets a test flip it later. */
export function stubSystemTheme(dark: boolean): { set: (dark: boolean) => void } {
    let matches = dark
    const listeners = new Set<() => void>()
    vi.stubGlobal(
        'matchMedia',
        vi.fn((query: string) => ({
            get matches() {
                return query.includes('dark') ? matches : false
            },
            media: query,
            addEventListener: (_: string, listener: () => void) => listeners.add(listener),
            removeEventListener: (_: string, listener: () => void) => listeners.delete(listener),
        })),
    )
    return {
        set(next) {
            matches = next
            for (const listener of listeners) {
                listener()
            }
        },
    }
}

/** Plays another tab writing `value` under `key`, or removing it for null, as the browser then tells this one. */
export function otherTab(key: string, value: string | null): void {
    if (value === null) {
        localStorage.removeItem(key)
    } else {
        localStorage.setItem(key, value)
    }
    globalThis.dispatchEvent(new StorageEvent('storage', { key, newValue: value }))
}

/** Plays another tab clearing all of storage, which the browser reports with no key. */
export function otherTabClears(): void {
    localStorage.clear()
    globalThis.dispatchEvent(new StorageEvent('storage', { key: null }))
}

/** Makes every use of localStorage throw, as a privacy mode can. */
export function breakStorage(): void {
    vi.stubGlobal('localStorage', { getItem: refuse, setItem: refuse, removeItem: refuse, clear: refuse })
}

/** Stands in for EventSource: records instances, and lets a test play the server. */
export class FakeEventSource extends EventTarget {
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

    refuse(): void {
        this.readyState = FakeEventSource.CLOSED
        this.dispatchEvent(new Event('error'))
    }

    close(): void {
        this.closed = true
        this.readyState = FakeEventSource.CLOSED
    }
}

function refuse(): never {
    throw new DOMException('storage is disabled', 'SecurityError')
}
