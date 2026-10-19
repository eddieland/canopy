import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { mockAttention } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { AttentionItem, RunsSince } from '@/api/types'
import { Toaster } from '@/components/toaster'
import { AWAY_MS } from '@/lib/away'

import { FRESH_WAIT_MS, useAwayNote } from './use-away-note'

const HIDDEN_AT = new Date('2026-10-08T14:05:00Z')
const asked = mockAttention[0] as AttentionItem
const failed: AttentionItem = { ...asked, id: 'a9', reason: 'worker_failed' }

let visibility: DocumentVisibilityState = 'visible'

beforeEach(() => {
    visibility = 'visible'
    vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility)
    vi.useFakeTimers()
    vi.setSystemTime(HIDDEN_AT)
})

afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.restoreAllMocks()
})

function Shell({ enabled }: { enabled: boolean }) {
    useAwayNote(enabled)
    return null
}

// A signed-in shell whose attention list is `items`, and whose server counts `runs` since the tab was hidden.
function shell(items: AttentionItem[], runs: RunsSince, enabled = true) {
    // Reads nothing it holds again, and drops nothing however long the tab is away, so the runs counted come from the
    // cache, as a test cannot serve them.
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, gcTime: Infinity } } })
    client.setQueryData(keys.attention, items)
    client.setQueryData(keys.runsSince(HIDDEN_AT.toISOString()), runs)
    render(
        <QueryClientProvider client={client}>
            <Toaster>
                <Shell enabled={enabled} />
            </Toaster>
        </QueryClientProvider>,
    )
    return client
}

function show(state: DocumentVisibilityState): void {
    act(() => {
        visibility = state
        document.dispatchEvent(new Event('visibilitychange'))
    })
}

// The tab hidden for `ms`, then shown again.
function away(ms: number): void {
    show('hidden')
    act(() => {
        vi.advanceTimersByTime(ms)
    })
    show('visible')
}

// The stream sends the attention list again, as it does on starting over, and what that sets off runs: the cache tells
// its listeners on the next timer's turn.
async function streamSends(client: QueryClient, items: AttentionItem[]): Promise<void> {
    await act(async () => {
        client.setQueryData(keys.attention, items)
        await vi.advanceTimersByTimeAsync(1)
    })
}

function toasts(): string[] {
    const region = screen.getByRole('region', { name: 'Notifications (F8)' })
    return within(region)
        .queryAllByRole('listitem')
        .map((toast) => toast.textContent)
}

describe('useAwayNote', () => {
    it('says what changed once the list read after a long absence arrives, and not before', async () => {
        const client = shell([asked], { ended: 3, prs_opened: 2 })
        away(AWAY_MS)
        expect(toasts()).toEqual([])

        await streamSends(client, [failed])
        expect(toasts()).toEqual([
            expect.stringMatching(
                /^Since \d\d:\d\d: 1 new item needs you, 1 item cleared, 2 PRs opened, 3 runs ended$/u,
            ),
        ])
    })

    it('says nothing after a short absence, whatever changed', async () => {
        const client = shell([asked], { ended: 3, prs_opened: 2 })
        away(AWAY_MS - 1)
        await streamSends(client, [failed])
        expect(toasts()).toEqual([])
    })

    it('says nothing when nothing changed', async () => {
        const client = shell([asked], { ended: 0, prs_opened: 0 })
        away(AWAY_MS)
        await streamSends(client, [asked])
        expect(toasts()).toEqual([])
    })

    it('drops the note when no fresh list arrives in time, rather than tell it from the old one', async () => {
        const client = shell([asked], { ended: 3, prs_opened: 2 })
        away(AWAY_MS)
        act(() => {
            vi.advanceTimersByTime(FRESH_WAIT_MS)
        })
        await streamSends(client, [failed])
        expect(toasts()).toEqual([])
    })

    it('drops the note when the tab is hidden again before the list arrives', async () => {
        const client = shell([asked], { ended: 3, prs_opened: 2 })
        away(AWAY_MS)
        show('hidden')
        await streamSends(client, [failed])
        expect(toasts()).toEqual([])
    })

    it('does nothing while signed out', async () => {
        const client = shell([asked], { ended: 3, prs_opened: 2 }, false)
        away(AWAY_MS)
        await streamSends(client, [failed])
        expect(toasts()).toEqual([])
    })
})
