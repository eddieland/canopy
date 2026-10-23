import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockAttention, mockRuns, mockTasks, mockTickets } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { AttentionItem, Run, TaskSummary, TicketSummary } from '@/api/types'
import { DEFAULT_CLOCK } from '@/lib/clock'
import { localTime } from '@/lib/time'
import { tipOf } from '@/test-utils'

import { Counters } from './counters'

afterEach(() => {
    cleanup()
})

// Renders the counters over the lists given, and nothing fetched: a list left out has not arrived.
function renderCounters({
    runs,
    tickets,
    tasks,
    attention,
}: {
    runs?: Run[]
    tickets?: TicketSummary[]
    tasks?: TaskSummary[]
    attention?: AttentionItem[]
}) {
    const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
    client.setQueryData(keys.runs, runs)
    client.setQueryData(keys.tickets, tickets)
    client.setQueryData(keys.tasks, tasks)
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

    it('counts the running runs, with nothing under them that the next counter says', () => {
        renderCounters({ runs: mockRuns })
        expect(counter('running').textContent).toBe('Running1')
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
        expect(tipOf(waiting.getByRole('time'))).toBe(localTime('2026-10-08T10:00:00Z', DEFAULT_CLOCK))
    })

    it('counts a ticket whose feedback plan waits on your approval, once though a question waits too', () => {
        const plan = { id: 3, pr_urls: ['https://github.com/acme/web/pull/88'], items: 2, stale: false }
        renderCounters({
            tickets: [
                { ...ticket('ABC-099', null), feedback_plan: plan },
                { ...ticket('ABC-102', 5), feedback_plan: plan },
                ticket('ABC-104', null),
            ],
            attention: [],
        })
        expect(within(counter('waiting')).getByText('2')).toBeDefined()
    })

    it("counts a task's run running among the runs", () => {
        renderCounters({ runs: mockRuns, tasks: mockTasks })
        // Run 41, and task 6's run.
        expect(counter('running').textContent).toBe('Running2')
    })

    it('counts a task waiting on your reply, and dates its question with the tickets', () => {
        const asks = { ...question('task:4', '2026-10-08T08:00:00Z'), ticket_key: null, task: 4 }
        renderCounters({
            tickets: [ticket('ABC-102', 5)],
            tasks: mockTasks,
            attention: [question('ABC-102', '2026-10-08T11:56:00Z'), asks],
        })
        const waiting = within(counter('waiting'))
        expect(waiting.getByText('2')).toBeDefined()
        expect(tipOf(waiting.getByRole('time'))).toBe(localTime('2026-10-08T08:00:00Z', DEFAULT_CLOCK))
    })

    it("drops a task's question from the count and the age once it is replied to", () => {
        const asks = { ...question('task:4', '2026-10-08T08:00:00Z'), ticket_key: null, task: 4 }
        const replied: TaskSummary[] = [{ ...(mockTasks[2] as TaskSummary), standing: 'queued', question_id: null }]
        renderCounters({ tickets: [ticket('ABC-104', null)], tasks: replied, attention: [asks] })
        const waiting = within(counter('waiting'))
        expect(waiting.getByText('0')).toBeDefined()
        expect(waiting.getByText('no question open')).toBeDefined()
    })

    it('says no question is open when every question has been answered', () => {
        renderCounters({ tickets: [ticket('ABC-104', null)], attention: [question('ABC-104', '2026-10-08T09:00:00Z')] })
        expect(within(counter('waiting')).getByText('no question open')).toBeDefined()
    })

    it("counts the attention list, and leaves how it splits to the nav's badge", () => {
        const broken = { ...mockAttention[0], id: 'a2', reason: 'worker_failed' } as AttentionItem
        const finding = { ...mockAttention[0], id: 'a3', reason: 'deps', finding: true } as AttentionItem
        renderCounters({ attention: [...mockAttention, broken, finding] })
        expect(counter('attention').textContent).toBe('Attention3')
    })

    it('says waiting on you once, in the counter that counts it', () => {
        renderCounters({ runs: mockRuns, tickets: mockTickets, attention: mockAttention })
        expect(screen.getAllByText(/waiting on you/iu)).toHaveLength(1)
    })
})
