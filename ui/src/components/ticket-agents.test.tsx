import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import type { AgentModel, AgentPersona } from '@/api/types'

import { TicketAgents } from './ticket-agents'

const PERSONAS: AgentPersona[] = [
    { agent: 'worker', persona: 'minimalist', source: 'ticket', error: null, once: null, several: [] },
    { agent: 'planner', persona: 'skeptic', source: 'config', error: null, once: null, several: [] },
    { agent: 'reviewer', persona: 'canopy', source: 'default', error: null, once: null, several: [] },
]
const MODELS: AgentModel[] = [
    {
        agent: 'worker',
        model: 'acme/deep-2',
        source: 'ticket',
        variant: null,
        dropped_variant: null,
        last_served: null,
    },
    { agent: 'planner', model: null, source: 'default', variant: null, dropped_variant: null, last_served: null },
    { agent: 'reviewer', model: null, source: 'default', variant: null, dropped_variant: null, last_served: null },
]

// The personas the menus describe, the one read the rows send before anything is chosen.
const server: Middleware = {
    onRequest() {
        return Response.json({ reviewer: 'canopy', personas: [] })
    },
}

beforeEach(() => {
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

describe('TicketAgents', () => {
    it("lays out a row per agent, its persona and then its model, each named as the agent's", () => {
        render(
            <QueryClientProvider client={new QueryClient()}>
                <TicketAgents
                    ticketKey="ABC-1"
                    personas={PERSONAS}
                    names={['canopy', 'minimalist', 'skeptic']}
                    models={MODELS}
                />
            </QueryClientProvider>,
        )
        expect(screen.getAllByRole('term').map((label) => label.textContent)).toEqual(['worker', 'planner', 'reviewer'])
        // Each agent's two menus follow its name, persona first.
        const menus = within(screen.getByTestId('ticket-agents'))
            .getAllByRole('button')
            .map((button) => button.getAttribute('aria-label'))
        expect(menus).toEqual([
            'worker persona: minimalist',
            'worker model: acme/deep-2',
            'planner persona: skeptic',
            'planner model: runtime default',
            'reviewer persona: canopy',
            'reviewer model: runtime default',
        ])
    })
})
