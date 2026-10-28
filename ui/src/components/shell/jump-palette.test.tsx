import { QueryClient } from '@tanstack/react-query'
import { act, cleanup, fireEvent, screen, within } from '@testing-library/react'
import type { AnyRouter } from '@tanstack/react-router'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { keys } from '@/api/queries'
import { mockTickets } from '@/api/mocks'
import type { TicketSummary } from '@/api/types'
import { parseRecent, STORAGE_KEY } from '@/lib/recent-tickets'
import { renderRouted } from '@/test-utils'

import { JumpPalette } from './jump-palette'

const BASE = mockTickets[0] as TicketSummary

// Three tickets: one waiting on the operator, one a run is working, one done.
const TICKETS: TicketSummary[] = [
    { ...BASE, key: 'ABC-1', title: 'Export reports as CSV', awaiting: 5, active_at: '2026-10-08T11:00:00Z' },
    {
        ...BASE,
        key: 'ABC-2',
        title: 'Debounce the search box',
        awaiting: null,
        running_run: 39,
        active_at: '2026-10-08T11:30:00Z',
    },
    {
        ...BASE,
        key: 'ABC-3',
        title: 'Drop the v1 client',
        awaiting: null,
        done: true,
        active_at: '2026-10-08T10:00:00Z',
    },
]

// The operator viewed ABC-2, then ABC-1, and once a ticket the journal has since forgotten.
const RECENT = [
    { key: 'ABC-1', title: 'Export reports as CSV', viewedAt: '2026-10-08T11:58:00Z' },
    { key: 'GONE-1', title: 'Forgotten', viewedAt: '2026-10-08T11:50:00Z' },
    { key: 'ABC-2', title: 'Debounce the search box', viewedAt: '2026-10-08T11:40:00Z' },
]

beforeEach(() => {
    localStorage.clear()
})

afterEach(cleanup)

// The palette in a shell that keeps whether it is open, as AppShell does.
function Shell() {
    const [open, setOpen] = useState(false)
    return <JumpPalette open={open} onOpenChange={setOpen} />
}

// The palette over the tickets the list query holds, after the operator viewed `recent`.
async function renderPalette(recent: readonly object[] = RECENT): Promise<AnyRouter> {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(recent))
    // The list as the stream sent it: never read again from a server, which a unit test has none of.
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } })
    client.setQueryData(keys.tickets, TICKETS)
    const { router } = await renderRouted(<Shell />, { at: '/attention', client })
    return router
}

function pressJump() {
    fireEvent.keyDown(globalThis.window, { key: 'k', ctrlKey: true })
}

function field(): HTMLElement {
    return screen.getByRole('combobox', { name: 'Jump to a ticket' })
}

function options(): string[] {
    return screen.getAllByRole('option').map((o) => o.textContent)
}

describe('JumpPalette', () => {
    it('opens on Ctrl+K on the tickets viewed last, newest first, each as it stands now', async () => {
        await renderPalette()
        expect(screen.queryByRole('dialog')).toBeNull()

        act(pressJump)
        const dialog = screen.getByRole('dialog', { name: 'Jump to a ticket' })
        expect(document.activeElement).toBe(field())
        const recent = within(dialog).getByRole('group', { name: 'Recent' })
        const rows = within(recent).getAllByRole('option')
        expect(rows.map((r) => r.dataset['testid'])).toEqual(['jump-ABC-1', 'jump-ABC-2'])
        expect(rows[0]?.textContent).toContain('waiting on you')
        expect(rows[1]?.textContent).toContain('run:39')

        act(pressJump)
        expect(screen.queryByRole('dialog')).toBeNull()
    })

    it('drops a ticket the journal no longer holds, from the list and the store', async () => {
        await renderPalette()
        act(pressJump)
        expect(options().some((o) => o.includes('GONE-1'))).toBe(false)
        expect(parseRecent(localStorage.getItem(STORAGE_KEY)).map((t) => t.key)).toEqual(['ABC-1', 'ABC-2'])
    })

    it('keeps a ticket viewed after the tickets list was read, which that list cannot know', async () => {
        // Viewed a minute from now: after the list the test seeds, as a ticket opened from a link before the stream
        // sent the list again.
        const later = new Date(Date.now() + 60_000).toISOString()
        await renderPalette([{ key: 'NEW-1', title: 'Just made', viewedAt: later }, ...RECENT])
        act(pressJump)
        expect(options()[0]).toContain('NEW-1')
        expect(parseRecent(localStorage.getItem(STORAGE_KEY)).map((t) => t.key)).toEqual(['NEW-1', 'ABC-1', 'ABC-2'])
    })

    it('opens the ticket the keys are on with Enter, and closes', async () => {
        const router = await renderPalette()
        act(pressJump)
        await act(async () => {
            fireEvent.keyDown(field(), { key: 'Enter' })
            await router.invalidate()
        })
        expect(router.state.location.pathname).toBe('/tickets/ABC-1')
        expect(screen.queryByRole('dialog')).toBeNull()
    })

    it('narrows the recent tickets by what is typed, and lists the other tickets that match under them', async () => {
        await renderPalette()
        act(pressJump)
        fireEvent.change(field(), { target: { value: 'the' } })
        expect(within(screen.getByRole('group', { name: 'Recent' })).getAllByRole('option')).toHaveLength(1)
        expect(options()[0]).toContain('ABC-2')
        const others = within(screen.getByRole('group', { name: 'Tickets' })).getAllByRole('option')
        expect(others.map((o) => o.dataset['testid'])).toEqual(['jump-ABC-3'])
        expect(others[0]?.textContent).toContain('done')
    })

    it('offers the journal search when no ticket matches', async () => {
        const router = await renderPalette()
        act(pressJump)
        fireEvent.change(field(), { target: { value: 'stale requests' } })
        screen.getByText('no ticket with “stale requests” in the key or title')
        await act(async () => {
            fireEvent.click(screen.getByRole('option', { name: /Search the journal for/u }))
            await router.invalidate()
        })
        expect(router.state.location.href).toBe('/search?q=stale+requests')
    })

    it('says where viewed tickets will show before any is', async () => {
        await renderPalette([])
        act(pressJump)
        screen.getByText('Tickets you open show up here. Type to find any ticket.')
        expect(screen.queryAllByRole('option')).toHaveLength(0)
    })
})
