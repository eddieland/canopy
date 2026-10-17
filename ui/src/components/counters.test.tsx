import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockAttention, mockRuns, mockTickets } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { AttentionItem, Run, TicketSummary } from '@/api/types'
import { localTime } from '@/lib/time'

import { Counters } from './counters'

afterEach(() => {
    cleanup()
})

// Renders the counters over the lists given, and nothing fetched: a list left out has not arrived.
function renderCounters({
    runs,
    tickets,
    attention,
}: {
    runs?: Run[]
    tickets?: TicketSummary[]
    attention?: AttentionItem[]
}) {
    const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
    client.setQueryData(keys.runs, runs)
    client.setQueryData(keys.tickets, tickets)
    client.setQueryData(keys.attention, attention)
    return render(
        <QueryClientProvider client={client}>
            <Counters />
        </QueryClientProvider>,
    )
}

function counter(name: string) {
    return screen.getByTestId(`counter-${name}`)
}

function question(key: string, since: string): AttentionItem {
    return { ...mockAttention[0], id: key, subject: key, ticket_key: key, since } as AttentionItem
}

function ticket(key: string, awaiting: number | null): TicketSummary {
    return { ...mockTickets[0], key, awaiting } as TicketSummary
}

describe('Counters', () => {
    it('claims no count before its list arrives, not even a zero', () => {
        renderCounters({})
        expect(counter('running').textContent).toBe('Running')
        expect(within(counter('waiting')).queryByText(/\d/u)).toBeNull()
        expect(counter('attention').textContent).toBe('Attention')
    })

    it('counts the running runs, and under them the tickets whose latest run waits on you', () => {
        const { unmount } = renderCounters({ runs: mockRuns })
        expect(within(counter('running')).getByText('1')).toBeDefined()
        expect(within(counter('running')).getByText('1 waiting on you')).toBeDefined()
        unmount()

        // A later run on the blocked ticket took its question up: the ticket waits on nothing now.
        const [running, blocked] = mockRuns
        const later = { ...running, id: 43, ticket_key: 'ABC-102' } as Run
        renderCounters({ runs: [running, later, blocked] as Run[] })
        expect(within(counter('running')).getByText('2')).toBeDefined()
        expect(within(counter('running')).getByText('0 waiting on you')).toBeDefined()
    })

    it('counts the tickets waiting on you, and dates the oldest question no one has answered yet', () => {
        renderCounters({
            tickets: [ticket('ABC-102', 5), ticket('ABC-103', 7), ticket('ABC-104', null)],
            attention: [
                question('ABC-102', '2026-10-08T11:56:00Z'),
                question('ABC-103', '2026-10-08T10:00:00Z'),
                // Answered, so it waits on the next tick, not on you, though it is the oldest on the list.
                question('ABC-104', '2026-10-08T09:00:00Z'),
            ],
        })
        const waiting = within(counter('waiting'))
        expect(waiting.getByText('2')).toBeDefined()
        expect(waiting.getByText(/^oldest/u)).toBeDefined()
        expect(waiting.getByTitle(localTime('2026-10-08T10:00:00Z'))).toBeDefined()
    })

    it('says no question is open when every question has been answered', () => {
        renderCounters({ tickets: [ticket('ABC-104', null)], attention: [question('ABC-104', '2026-10-08T09:00:00Z')] })
        expect(within(counter('waiting')).getByText('no question open')).toBeDefined()
    })

    it('counts the attention list, and breaks it down by what broke, what waits on you, and the rest', () => {
        const broken = { ...mockAttention[0], id: 'a2', reason: 'worker_failed' } as AttentionItem
        const finding = { ...mockAttention[0], id: 'a3', reason: 'deps', finding: true } as AttentionItem
        const { unmount } = renderCounters({ attention: [...mockAttention, broken, finding] })
        expect(within(counter('attention')).getByText('3')).toBeDefined()
        expect(within(counter('attention')).getByText('1 broken, 1 waiting on you, 1 other')).toBeDefined()
        unmount()

        renderCounters({ attention: [] })
        expect(within(counter('attention')).getByText('nothing')).toBeDefined()
    })
})
