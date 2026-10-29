import { QueryClient } from '@tanstack/react-query'
import { cleanup, screen } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import type { SpendModel } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { TicketCanary } from './ticket-canary'

// One kind's spend on a model over the window.
function spent(kind: SpendModel['kind'], model: string | null, runs: number, cost: number): SpendModel {
    return { kind, model, runs, replies: runs * 10, cost_usd: cost }
}

/** ABC-1's runs: its workers on two models, its reviewer on a third, and a run not read yet. */
const OWN = [
    spent('workers', 'openai/gpt-5@high', 2, 2.2),
    spent('workers', 'openai/gpt-5', 1, 0.7),
    spent('workers', null, 1, 0.4),
    spent('reviews', 'anthropic/claude-haiku-4-5', 2, 0.1),
]
/** Every run's: the workspace's workers on the same models, and the overseer's on one of them. */
const EVERY = [
    spent('overseer', 'openai/gpt-5', 40, 9),
    spent('workers', 'openai/gpt-5@high', 8, 7.04),
    spent('workers', 'openai/gpt-5', 10, 6),
]

// Each read the line sends, by its query, and what the server stand-in answers with: `own` for the ticket's.
let read: string[] = []
let own: SpendModel[] = OWN

const server: Middleware = {
    onRequest({ request }) {
        const url = new URL(request.url)
        read.push(url.search)
        const ticket = url.searchParams.get('ticket')
        return Response.json({ since: '2026-10-01T00:00:00Z', days: 30, ticket, models: ticket ? own : EVERY })
    },
}

beforeEach(() => {
    read = []
    own = OWN
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

function renderCanary(override = false) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return renderRouted(<TicketCanary ticketKey="ABC-1" override={override} />, { client })
}

describe('TicketCanary', () => {
    it("sets each model's cost per worker run beside the workspace's, its reviewer's model left out", async () => {
        await renderCanary()
        // Once the workspace's read is in, as the ticket's is.
        await screen.findByText(/workspace \$0\.60/u)
        expect(screen.getAllByTestId('ticket-canary-model').map((row) => row.textContent)).toEqual([
            'openai/gpt-5@high2 runs, $1.10/run · workspace $0.88/run',
            'openai/gpt-51 run, $0.70/run · workspace $0.60/run',
        ])
        expect(screen.getByRole('link', { name: 'Its last 30 days by model, on Spend' }).getAttribute('href')).toBe(
            '/reports/spend?days=30&ticket=ABC-1',
        )
        expect(read).toEqual(['?days=30&ticket=ABC-1', '?days=30'])
    })

    it('shows nothing for workers one model served while nothing overrides it, reading no workspace', async () => {
        own = [OWN[0] as SpendModel, OWN[3] as SpendModel]
        const { container } = await renderCanary()
        await expect.poll(() => read).toEqual(['?days=30&ticket=ABC-1'])
        expect(container.querySelector('[data-testid="ticket-canary"]')).toBeNull()
    })

    it('shows the one model while the ticket overrides its workers, the canary set', async () => {
        own = [OWN[0] as SpendModel]
        await renderCanary(true)
        const rows = await screen.findAllByTestId('ticket-canary-model')
        expect(rows).toHaveLength(1)
    })
})
