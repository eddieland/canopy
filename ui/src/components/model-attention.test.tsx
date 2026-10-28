import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import type { AgentModel } from '@/api/types'

import { ModelAttention } from './model-attention'

const MODELS: AgentModel[] = [
    {
        agent: 'worker',
        model: 'acme/gone-1',
        source: 'ticket',
        variant: null,
        dropped_variant: null,
        last_served: null,
    },
    {
        agent: 'planner',
        model: 'acme/fast-1',
        source: 'config',
        variant: null,
        dropped_variant: null,
        last_served: null,
    },
    { agent: 'reviewer', model: null, source: 'default', variant: null, dropped_variant: null, last_served: null },
]

// The paths the block reads, with their queries; the server stand-in answers each with the runtime's list.
let read: string[] = []

const server: Middleware = {
    onRequest({ request }) {
        const url = new URL(request.url)
        read.push(url.pathname + url.search)
        return Response.json({ models: ['acme/fast-1', 'acme/deep-2'], error: null })
    },
}

beforeEach(() => {
    read = []
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

function renderBlock() {
    return render(
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
            <ModelAttention ticketKey="ABC-1" models={MODELS} />
        </QueryClientProvider>,
    )
}

describe('ModelAttention', () => {
    it("reads the runtime's list as it opens, and marks the model it no longer lists with no menu open", async () => {
        renderBlock()
        expect(screen.getByRole('region', { name: 'Models' })).toBeTruthy()
        const gone = await screen.findByRole('button', {
            name: 'worker model: acme/gone-1, no longer listed; its next run is refused',
        })
        expect(gone.title).toBe('no longer listed; its next run is refused')
        expect(screen.getByRole('button', { name: 'planner model: acme/fast-1' })).toBeTruthy()
        // Fresh from the runtime, not the list the server kept, which may still name the model gone.
        expect(read).toEqual(['/api/models?refresh=true'])
    })
})
