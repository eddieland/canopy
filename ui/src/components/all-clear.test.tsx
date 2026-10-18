import { QueryClient } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockTickets } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { TicketSummary } from '@/api/types'
import { StreamContext } from '@/hooks/use-loop-down'
import { renderRouted } from '@/test-utils'

import { AllClear, EmptyAttention } from './all-clear'

afterEach(cleanup)

describe('AllClear', () => {
    it('says nothing needs the operator while the loop answers', () => {
        render(<AllClear />)
        expect(screen.getByTestId('all-clear').textContent).toContain('Nothing needs you.')
    })

    it("says nothing needed them as of the drop, and never celebrates, while the loop isn't answering", async () => {
        render(
            <StreamContext value={{ status: 'reconnecting', downSince: Date.now() - 60_000 }}>
                <AllClear />
            </StreamContext>,
        )
        await waitFor(() => {
            expect(screen.getByTestId('all-clear').textContent).toMatch(/^Nothing needed you as of .+\./u)
        })
        expect(screen.getByTestId('all-clear').textContent).not.toContain('all clear')
    })
})

function renderEmpty(tickets: TicketSummary[] | undefined) {
    const client = new QueryClient()
    // Nothing is fetched: the tickets and the latest tick are what the test seeds.
    client.setQueryDefaults(keys.tickets, { enabled: false })
    client.setQueryDefaults(keys.tick, { enabled: false })
    if (tickets !== undefined) {
        client.setQueryData(keys.tickets, tickets)
    }
    client.setQueryData(keys.tick, { tick: null, acknowledged: null })
    return renderRouted(<EmptyAttention />, { client })
}

describe('EmptyAttention', () => {
    it('names the first step, not all clear, while the journal holds no ticket', async () => {
        const { router } = await renderEmpty([])
        expect(screen.getByTestId('first-run').textContent).toBe(
            'no tickets yet: give one your queue label in the tracker, or start one privately on Tickets, ' +
                'then Tick now',
        )
        expect(screen.queryByTestId('all-clear')).toBeNull()
        expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Tick now' }).disabled).toBe(false)

        await act(async () => {
            fireEvent.click(screen.getByRole('link', { name: 'Tickets' }))
            await Promise.resolve()
        })
        expect(router.state.location.pathname).toBe('/tickets')
    })

    it('is all clear once there was work and none of it is listed', async () => {
        await renderEmpty(mockTickets)
        expect(screen.getByTestId('all-clear').textContent).toContain('Nothing needs you.')
        expect(screen.queryByTestId('first-run')).toBeNull()
    })

    it('says neither until the tickets are read', async () => {
        await renderEmpty(undefined)
        expect(screen.getByTestId('panel-skeleton')).toBeDefined()
        expect(screen.queryByTestId('all-clear')).toBeNull()
        expect(screen.queryByTestId('first-run')).toBeNull()
    })
})
