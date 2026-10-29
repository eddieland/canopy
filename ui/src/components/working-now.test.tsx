import { QueryClient } from '@tanstack/react-query'
import { cleanup, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockRuns } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { Run } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { WorkingNow } from './working-now'

afterEach(() => {
    cleanup()
})

const [RUNNING, BLOCKED] = mockRuns as [Run, Run]

// A client holding `runs` as the stream wrote them, which reads nothing itself.
function client(runs: Run[]): QueryClient {
    const queries = new QueryClient()
    queries.setQueryDefaults(keys.runs, { enabled: false })
    queries.setQueryDefaults(keys.meta, { enabled: false })
    queries.setQueryData(keys.runs, runs)
    return queries
}

// Each run's row, not the entries of its progress's checklist inside it.
function working(): HTMLElement[] {
    const list = screen.getByTestId('working-now')
    return within(list)
        .queryAllByRole('listitem')
        .filter((item) => item.parentElement === list)
}

describe('WorkingNow', () => {
    it('names the run working the ticket now, what it is doing, and what it has cost', async () => {
        const other = { ...RUNNING, id: 44, ticket_key: 'ABC-200' }
        await renderRouted(<WorkingNow ticketKey="ABC-101" />, { client: client([RUNNING, other, BLOCKED]) })
        const [row] = working()
        expect(working()).toHaveLength(1)
        const run = within(row as HTMLElement)
        expect(run.getByText('working now')).toBeDefined()
        expect(run.getByRole('link', { name: 'run:41' }).getAttribute('href')).toBe('/runs/41')
        expect(run.getByText('npm test -- login')).toBeDefined()
        expect(run.getByText('$0.42')).toBeDefined()
    })

    it('says nothing while no run works the ticket, even one that waits on the operator', async () => {
        await renderRouted(<WorkingNow ticketKey="ABC-102" />, { client: client(mockRuns) })
        expect(working()).toHaveLength(0)
    })

    it('appears when the stream says a run started on the ticket, and leaves when it ends', async () => {
        const queries = client([BLOCKED])
        await renderRouted(<WorkingNow ticketKey="ABC-102" />, { client: queries })
        expect(working()).toHaveLength(0)

        const started = { ...BLOCKED, id: 45, status: 'running', state: 'running', ended_at: null } as const
        queries.setQueryData(keys.runs, [started, BLOCKED])
        expect(await screen.findByRole('link', { name: 'run:45' })).toBeDefined()

        queries.setQueryData(keys.runs, [{ ...started, status: 'done', state: 'done' }, BLOCKED])
        await waitFor(() => {
            expect(working()).toHaveLength(0)
        })
    })
})
