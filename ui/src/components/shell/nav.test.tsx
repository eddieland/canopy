import { QueryClient } from '@tanstack/react-query'
import { act, cleanup, fireEvent, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockAttention } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { AttentionItem } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { Nav } from './nav'

afterEach(cleanup)

const WAITING = mockAttention[0] as AttentionItem
// One run that failed, one question waiting on the operator, and a finding: one of each part of the count.
const ITEMS: AttentionItem[] = [
    { ...WAITING, id: 'a2', reason: 'worker_failed', detail: 'run 40 failed' },
    WAITING,
    { ...WAITING, id: 'a3', reason: 'finding', finding: true, chore: 'deps', ticket_key: null },
]

function renderNav({ at = '/attention', items, compact = false }: Partial<NavSetup> = {}) {
    const client = new QueryClient()
    // Nothing is fetched: the attention list is what the test seeds, as the stream would send it.
    client.setQueryDefaults(keys.attention, { enabled: false })
    if (items !== undefined) {
        client.setQueryData(keys.attention, items)
    }
    return renderRouted(<Nav compact={compact} />, { at, client })
}

interface NavSetup {
    at: string
    items: AttentionItem[] | undefined
    compact: boolean
}

// The links the nav marks as the page shown.
function current(): string[] {
    return screen
        .getAllByRole('link')
        .filter((link) => link.getAttribute('aria-current') === 'page')
        .map((link) => link.textContent)
}

describe('Nav', () => {
    it.each([
        ['a ticket', '/tickets/ABC-102', 'Tickets'],
        ['a PR', '/pull-requests/pr?url=x', 'Pull requests'],
        ['a review', '/reviews/4', 'Reviews'],
        ['a chore', '/chores/deps', 'Chores'],
        ['a tick', '/ticks/12', 'Ticks'],
        ['the runs list', '/runs', 'Runs'],
    ] as const)("keeps its section current on %s's page", async (_, at, section) => {
        await renderNav({ at, items: [] })
        expect(current()).toEqual([section])
    })

    it('marks no section on a page in none', async () => {
        await renderNav({ at: '/no-such-page', items: [] })
        expect(current()).toEqual([])
    })

    it('opens the page of the section followed', async () => {
        const { router } = await renderNav({ items: [] })
        await act(async () => {
            fireEvent.click(screen.getByRole('link', { name: 'Spend' }))
            await Promise.resolve()
        })
        expect(router.state.location.pathname).toBe('/spend')
    })

    it("splits Attention's count as its counter does, in words for a screen reader and on hover", async () => {
        await renderNav({ at: '/runs', items: [...ITEMS, WAITING] })
        expect(screen.getByRole('link', { name: 'Attention 1 broken, 2 waiting on you, 1 other' })).toBeDefined()
        expect(screen.getByTitle('1 broken, 2 waiting on you, 1 other')).toBeDefined()
        // The eye reads the three numbers, each in its part's color.
        expect(screen.getAllByText(/^\d$/u).map((count) => count.textContent)).toEqual(['1', '2', '1'])
    })

    it.each<[string, AttentionItem[] | undefined]>([
        ['the list is empty', []],
        ['the list has not arrived', undefined],
    ])('shows no count beside Attention when %s', async (_, items) => {
        await renderNav({ items })
        expect(screen.getByRole('link', { name: 'Attention' }).textContent).toBe('Attention')
    })

    it('names each icon in a compact nav, and gives Attention its total, said in words', async () => {
        await renderNav({ at: '/tickets/ABC-102', items: ITEMS, compact: true })
        expect(current()).toEqual(['Tickets'])
        expect(screen.getByRole('link', { name: 'Attention 1 broken, 1 waiting on you, 1 other' })).toBeDefined()
        expect(screen.getAllByText(/^\d$/u).map((count) => count.textContent)).toEqual(['3'])
        expect(screen.getByRole('link', { name: 'Settings' }).title).toBe(
            'Settings: The theme, the send key, the fun, and the session',
        )
    })
})
