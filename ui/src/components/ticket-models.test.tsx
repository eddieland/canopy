import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import type { AgentModel } from '@/api/types'

import { TicketModels } from './ticket-models'

const LISTED = ['acme/fast-1', 'acme/deep-2']
const MODELS: AgentModel[] = [
    { agent: 'worker', model: 'acme/deep-2', source: 'ticket' },
    { agent: 'planner', model: 'acme/fast-1', source: 'config' },
    { agent: 'reviewer', model: null, source: 'default' },
]

// Every request the panel sends, and what the server stand-in answers each: the list for a read, `answer` for a write.
let sent: { method: string; path: string; body: unknown }[] = []
let listed: Response | undefined
let answer: Response | undefined

const server: Middleware = {
    async onRequest({ request }) {
        const path = new URL(request.url).pathname
        const text = await request.text()
        sent.push({ method: request.method, path, body: text === '' ? null : (JSON.parse(text) as unknown) })
        if (request.method === 'GET') {
            return listed ?? Response.json({ models: LISTED, error: null })
        }
        return answer ?? Response.json({ agent: 'reviewer', model: 'acme/deep-2', source: 'ticket' })
    },
}

beforeEach(() => {
    sent = []
    listed = undefined
    answer = undefined
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

function renderModels(models: AgentModel[] = MODELS) {
    return render(
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
            <TicketModels ticketKey="ABC-1" models={models} />
        </QueryClientProvider>,
    )
}

function openMenu(name: string) {
    fireEvent.pointerDown(screen.getByRole('button', { name }), { button: 0, ctrlKey: false })
    return screen.getByRole('menu')
}

describe('TicketModels', () => {
    it("shows each agent's next model and where it comes from, in the CLI's words, reading no list", () => {
        renderModels()
        const rows = screen.getAllByTestId('ticket-model').map((row) => [row.textContent, row.title])
        expect(rows).toEqual([
            ['workeracme/deep-2override', "this ticket's override"],
            ['planneracme/fast-1', '[runtime.models]'],
            ["reviewerthe runtime's default", 'nothing sets one'],
        ])
        expect(sent).toEqual([])
    })

    it('reads the models when a menu opens and sets the override, as canopy model KEY MODEL --agent does', async () => {
        renderModels()
        const menu = openMenu("reviewer model: the runtime's default")
        const items = await within(menu).findAllByRole('menuitemradio')
        expect(items.map((item) => item.textContent)).toEqual(LISTED)
        // Nothing is checked while no override stands.
        expect(items.map((item) => item.getAttribute('aria-checked'))).toEqual(['false', 'false'])
        expect(within(menu).getByRole('menuitem', { name: 'Clear the override' }).getAttribute('aria-disabled')).toBe(
            'true',
        )
        fireEvent.click(within(menu).getByRole('menuitemradio', { name: 'acme/deep-2' }))
        expect(
            await screen.findByText(
                "ABC-1's reviewer runs use acme/deep-2 from their next run: this ticket's override.",
            ),
        ).toBeDefined()
        expect(sent).toEqual([
            { method: 'GET', path: '/api/models', body: null },
            { method: 'POST', path: '/api/tickets/ABC-1/models', body: { agent: 'reviewer', model: 'acme/deep-2' } },
        ])
    })

    it('clears an override standing, as --clear does', async () => {
        answer = Response.json({ agent: 'worker', model: null, source: 'default' })
        renderModels()
        const menu = openMenu('worker model: acme/deep-2')
        const chosen = await within(menu).findByRole('menuitemradio', { name: 'acme/deep-2' })
        expect(chosen.getAttribute('aria-checked')).toBe('true')
        fireEvent.click(within(menu).getByRole('menuitem', { name: 'Clear the override' }))
        expect(
            await screen.findByText(
                "ABC-1's worker runs use the runtime's default from their next run: nothing sets one.",
            ),
        ).toBeDefined()
        expect(sent.at(-1)).toEqual({
            method: 'POST',
            path: '/api/tickets/ABC-1/models',
            body: { agent: 'worker', model: null },
        })
    })

    it('says why the list could not be read, and keeps a model the runtime no longer lists checked', async () => {
        listed = Response.json({ models: [], error: '`opencode models` exited 1' })
        renderModels()
        const menu = openMenu('worker model: acme/deep-2')
        expect(await within(menu).findByText('Could not read its models: `opencode models` exited 1')).toBeDefined()
        const items = within(menu).getAllByRole('menuitemradio')
        expect(items.map((item) => [item.textContent, item.getAttribute('aria-checked')])).toEqual([
            ['acme/deep-2', 'true'],
        ])
    })

    it('names the guard of a refusal', async () => {
        answer = Response.json(
            { detail: { guard: 'unknown_model', reason: 'OpenCode does not list the model acme/fast-1' } },
            { status: 409 },
        )
        renderModels()
        const menu = openMenu("reviewer model: the runtime's default")
        fireEvent.click(await within(menu).findByRole('menuitemradio', { name: 'acme/fast-1' }))
        expect((await screen.findByRole('alert')).textContent).toBe(
            'refused (unknown_model): OpenCode does not list the model acme/fast-1',
        )
    })

    it('shows nothing for a ticket the server sent no models for', () => {
        const { container } = renderModels([])
        expect(container.childElementCount).toBe(0)
    })
})
