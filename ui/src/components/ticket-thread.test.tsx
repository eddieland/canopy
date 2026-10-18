import { QueryClient } from '@tanstack/react-query'
import { cleanup, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockTickets } from '@/api/mocks'
import type { Message, TicketDetail, TicketSummary } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { TicketThread } from './ticket-thread'

afterEach(() => {
    cleanup()
    localStorage.clear()
})

const TICKET = { ...mockTickets[0], awaiting: null } as TicketSummary

function said(id: number, body: string): Message {
    return {
        id,
        at: '2026-10-08T10:00:00Z',
        body,
        source: 'worker',
        kind: 'report',
        channel: 'run',
        answers: null,
        run_id: null,
        comment: null,
    }
}

const OLD = [said(1, 'Opened a PR on the old branch.'), said(2, 'CI is red on the old branch.')]
const NEW = said(4, 'Started over on a new branch.')

function detail(messages: Message[], forgottenMessageId: number | null): TicketDetail {
    return {
        ticket: TICKET,
        units: [],
        limits: [],
        runs: [],
        messages,
        forgotten_at: forgottenMessageId === null ? null : '2026-10-08T11:00:00Z',
        forgotten_message_id: forgottenMessageId,
        decisions: [],
        cost: { runs: 0, reviews: 0, priced: 0, cost_usd: null },
        drafts: [],
    }
}

function renderThread(shown: TicketDetail, order: 'oldest' | 'newest' = 'oldest') {
    // Nothing is fetched: no run works the ticket, and no tick has read a message.
    const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
    return renderRouted(<TicketThread detail={shown} order={order} />, { client })
}

// What each message shown says, in the order shown.
function bodies(): (string | undefined)[] {
    return screen
        .getAllByRole('listitem')
        .map((li) => [...OLD, NEW].find((m) => within(li).queryByText(m.body) !== null)?.body)
}

describe('TicketThread', () => {
    it('shows the whole conversation of a ticket never forgotten', async () => {
        await renderThread(detail([...OLD, NEW], null))
        expect(bodies()).toEqual([...OLD, NEW].map((m) => m.body))
        expect(screen.queryByText(/work forgotten/u)).toBeNull()
    })

    it('folds away what came before a forget, under a line saying when, and opens it on asking', async () => {
        await renderThread(detail([...OLD, NEW], 2))
        expect(bodies()).toEqual([NEW.body])
        expect(screen.getByText(/the loop reads only what came after/u).textContent).toMatch(/^work forgotten /u)

        fireEvent.click(screen.getByRole('button', { name: 'Show 2 earlier messages' }))
        expect(bodies()).toEqual([...OLD, NEW].map((m) => m.body))
        expect(screen.getByRole('button', { name: 'Hide 2 earlier messages' })).toBeDefined()
    })

    it('keeps the earlier messages at the oldest end when the conversation is flipped', async () => {
        await renderThread(detail([...OLD, NEW], 2), 'newest')
        fireEvent.click(screen.getByRole('button', { name: 'Show 2 earlier messages' }))
        expect(bodies()).toEqual([NEW, ...OLD.toReversed()].map((m) => m.body))
    })

    it('says nothing has been said since the forget, and still offers what came before', async () => {
        await renderThread(detail(OLD, 2))
        expect(screen.queryAllByRole('listitem')).toHaveLength(0)
        expect(screen.getByText(/^no messages since its work was forgotten/u)).toBeDefined()
        expect(screen.getByRole('button', { name: 'Show 2 earlier messages' })).toBeDefined()
    })
})
