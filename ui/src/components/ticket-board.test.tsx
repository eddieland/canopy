import { QueryClient } from '@tanstack/react-query'
import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockTickets } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { TicketSummary } from '@/api/types'
import { DONE_SHOWN } from '@/lib/ticket-board'
import { renderRouted } from '@/test-utils'

import { TicketBoard } from './ticket-board'

afterEach(() => {
    cleanup()
})

const base = mockTickets[0] as TicketSummary
const ticket = (fields: Partial<TicketSummary>): TicketSummary => ({
    ...base,
    awaiting: null,
    running_run: null,
    done: false,
    private: false,
    ...fields,
})

// Renders `ui` routed, with no tracker link to read: the cards' keys would ask the server for `tracker.ticket_url`.
function renderBoard(ui: ReactNode) {
    const client = new QueryClient()
    client.setQueryDefaults(keys.meta, { enabled: false })
    return renderRouted(ui, { client })
}

// The keys of the cards in the column named `name`, top to bottom.
function cards(name: string): string[] {
    const column = screen.getByRole('region', { name: new RegExp(`^${name} \\d+$`, 'u') })
    return within(column)
        .queryAllByRole('listitem')
        .map((card) => within(card).getAllByRole('link')[0]?.textContent ?? '')
}

describe('TicketBoard', () => {
    it('shows every stage in order, each with its count, an empty one saying so', async () => {
        await renderBoard(<TicketBoard tickets={[ticket({ key: 'A-1', phase: 'ci_red' })]} />)
        const board = screen.getByRole('region', { name: 'Tickets by stage' })
        const names = within(board)
            .getAllByRole('heading', { level: 3 })
            .map((h) => h.textContent)
        expect(names).toEqual(['to do0', 'plan0', 'working0', 'CI1', 'review0', 'approved0', 'done0'])
        expect(cards('CI')).toEqual(['A-1'])
        expect(within(screen.getByRole('region', { name: 'review 0' })).getByText('none')).toBeTruthy()
    })

    it('puts a ticket a run is on in working, its card naming the run and its phase', async () => {
        await renderBoard(<TicketBoard tickets={[ticket({ key: 'A-2', phase: 'ci_red', running_run: 43 })]} />)
        expect(cards('working')).toEqual(['A-2'])
        const card = within(screen.getByRole('region', { name: 'working 1' })).getByRole('listitem')
        expect(within(card).getByText('run:43')).toBeTruthy()
        expect(within(card).getByText('ci red')).toBeTruthy()
    })

    it('marks a private ticket and says when one waits on you', async () => {
        await renderBoard(<TicketBoard tickets={[ticket({ key: 'A-3', private: true, awaiting: 5 })]} />)
        const card = within(screen.getByRole('region', { name: 'to do 1' })).getByRole('listitem')
        expect(within(card).getByText('private')).toBeTruthy()
        expect(within(card).getByText('waiting on you')).toBeTruthy()
    })

    it('shows the most recent done tickets and links to the rest in the done list', async () => {
        // Newest first, as the server sends them: D-0 is the most recent.
        const done = Array.from({ length: DONE_SHOWN + 3 }, (_, i) =>
            ticket({
                key: `D-${i}`,
                done: true,
                active_at: new Date(Date.UTC(2026, 9, 8) - i * 3_600_000).toISOString(),
            }),
        )
        const { router } = await renderBoard(<TicketBoard tickets={done} />)
        expect(cards('done')).toEqual(done.slice(0, DONE_SHOWN).map((t) => t.key))
        fireEvent.click(screen.getByRole('link', { name: '+3 more done' }))
        await waitFor(() => {
            expect(router.state.location.search).toEqual({ show: 'done' })
        })
    })

    it('keeps the most recent done tickets when the order is flipped, oldest of them first', async () => {
        const done = Array.from({ length: DONE_SHOWN + 3 }, (_, i) =>
            ticket({
                key: `D-${i}`,
                done: true,
                active_at: new Date(Date.UTC(2026, 9, 8) - i * 3_600_000).toISOString(),
            }),
        )
        await renderBoard(<TicketBoard tickets={done.toReversed()} />)
        expect(cards('done')).toEqual(
            done
                .slice(0, DONE_SHOWN)
                .toReversed()
                .map((t) => t.key),
        )
    })
})
