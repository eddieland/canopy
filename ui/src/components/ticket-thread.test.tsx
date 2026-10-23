import { QueryClient } from '@tanstack/react-query'
import { cleanup, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockTickets } from '@/api/mocks'
import type { Message, TicketDetail, TicketForget, TicketSummary } from '@/api/types'
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
        task_run_id: null,
        comment: null,
    }
}

const OLD = [said(1, 'Opened a PR on the old branch.'), said(2, 'CI is red on the old branch.')]
const NEW = said(4, 'Started over on a new branch.')
const LATEST = said(6, 'Third time lucky.')
const PR = 'https://github.com/acme/web/pull/91'

function forgot(messageId: number | null, fields: Partial<TicketForget> = {}): TicketForget {
    return {
        at: '2026-10-08T11:00:00Z',
        channel: 'web',
        run_id: null,
        message_id: messageId,
        branch: null,
        prs: [],
        ...fields,
    }
}

function detail(messages: Message[], forgets: TicketForget[] = []): TicketDetail {
    return {
        ticket: TICKET,
        units: [],
        limits: [],
        runs: [],
        messages,
        forgets,
        decisions: [],
        cost: { runs: 0, reviews: 0, priced: 0, cost_usd: null },
        drafts: [],
        personas: [],
        persona_names: [],
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
        .map((li) => [...OLD, NEW, LATEST].find((m) => within(li).queryByText(m.body) !== null)?.body)
}

describe('TicketThread', () => {
    it('shows the whole conversation of a ticket never forgotten', async () => {
        await renderThread(detail([...OLD, NEW]))
        expect(bodies()).toEqual([...OLD, NEW].map((m) => m.body))
        expect(screen.queryByText(/work forgotten/u)).toBeNull()
    })

    it('folds away what came before a forget, under a line saying when, and opens it on asking', async () => {
        await renderThread(detail([...OLD, NEW], [forgot(2)]))
        expect(bodies()).toEqual([NEW.body])
        expect(screen.getByText(/the loop reads only what came after/u).textContent).toMatch(/^work forgotten /u)

        fireEvent.click(screen.getByRole('button', { name: 'Show 2 earlier messages' }))
        expect(bodies()).toEqual([...OLD, NEW].map((m) => m.body))
        expect(screen.getByRole('button', { name: 'Hide 2 earlier messages' })).toBeDefined()
    })

    it('keeps the earlier messages at the oldest end when the conversation is flipped', async () => {
        await renderThread(detail([...OLD, NEW], [forgot(2)]), 'newest')
        fireEvent.click(screen.getByRole('button', { name: 'Show 2 earlier messages' }))
        expect(bodies()).toEqual([NEW, ...OLD.toReversed()].map((m) => m.body))
    })

    it('heads each attempt with its own forget, what it dropped, and its own fold', async () => {
        const forgets = [
            forgot(2, { channel: 'cli', branch: 'agent/ABC-102-export', prs: [PR] }),
            forgot(4, { at: '2026-10-08T11:30:00Z' }),
        ]
        await renderThread(detail([...OLD, NEW, LATEST], forgets))
        expect(bodies()).toEqual([LATEST.body])
        const [first, second] = screen.getAllByTestId('forgotten')
        if (first === undefined || second === undefined) {
            throw new Error('a fold for each forget')
        }
        expect(within(first).getByText(/^work forgotten /u).textContent).toMatch(/ via cli$/u)
        expect(within(first).getByText('agent/ABC-102-export')).toBeDefined()
        expect(within(first).getByRole('link', { name: 'acme/web#91' })).toBeDefined()
        // Only the latest forget is where the loop's reading begins.
        expect(within(second).getByText(/^work forgotten /u).textContent).toMatch(
            / via web: the loop reads only what came after$/u,
        )
        expect(within(second).queryByText(/^dropped/u)).toBeNull()

        fireEvent.click(within(second).getByRole('button', { name: 'Show 1 earlier message' }))
        expect(bodies()).toEqual([NEW.body, LATEST.body])
        fireEvent.click(within(first).getByRole('button', { name: 'Show 2 earlier messages' }))
        expect(bodies()).toEqual([...OLD, NEW, LATEST].map((m) => m.body))
    })

    it('heads a forget made before forgets were recorded with when alone', async () => {
        await renderThread(detail([...OLD, NEW], [forgot(2, { channel: null, prs: null })]))
        expect(screen.getByText(/^work forgotten /u).textContent).toMatch(/ago: the loop reads only what came after$/u)
        expect(screen.queryByText(/^dropped/u)).toBeNull()
    })

    it('says nothing has been said since the forget, and still offers what came before', async () => {
        await renderThread(detail(OLD, [forgot(2)]))
        expect(screen.queryAllByRole('listitem')).toHaveLength(0)
        expect(screen.getByText(/^no messages since its work was forgotten/u)).toBeDefined()
        expect(screen.getByRole('button', { name: 'Show 2 earlier messages' })).toBeDefined()
    })
})
