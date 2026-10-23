import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import type { AgentModel } from '@/api/types'

import { TicketModels } from './ticket-models'

const LISTED = ['acme/fast-1', 'acme/deep-2']
const MODELS: AgentModel[] = [
    { agent: 'worker', model: 'acme/deep-2', source: 'ticket', variant: null },
    { agent: 'planner', model: 'acme/fast-1', source: 'config', variant: null },
    { agent: 'reviewer', model: null, source: 'default', variant: null },
]

// Every request the panel sends, and what the server stand-in answers each: the list for a read, `answer` for a write.
let sent: { method: string; path: string; body: unknown }[] = []
let listed: Response | undefined
let answer: Response | Promise<Response> | undefined

const server: Middleware = {
    async onRequest({ request }) {
        const path = new URL(request.url).pathname
        const text = await request.text()
        sent.push({ method: request.method, path, body: text === '' ? null : (JSON.parse(text) as unknown) })
        if (request.method === 'GET') {
            return listed ?? Response.json({ models: LISTED, error: null })
        }
        return answer ?? Response.json({ agent: 'reviewer', model: 'acme/deep-2', source: 'ticket', variant: null })
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
        // Where the model comes from is in the menu, for a keyboard or a touch that never sees the row's title.
        expect(within(menu).getByRole('menuitem', { name: 'Where it comes from: nothing sets one' })).toBeTruthy()
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
        answer = Response.json({ agent: 'worker', model: null, source: 'default', variant: null })
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

    it('says in the failure color why the list could not be read, offers no model, and reads it again', async () => {
        listed = Response.json({ models: [], error: '`opencode models` exited 1' })
        renderModels()
        const menu = openMenu('worker model: acme/deep-2')
        expect(await within(menu).findByText('Could not read its models: `opencode models` exited 1')).toBeDefined()
        // Every choice would be refused `model_list_failed`: none is offered, but clearing needs no list.
        expect(within(menu).queryAllByRole('menuitemradio')).toEqual([])
        expect(
            within(menu).getByRole('menuitem', { name: 'Clear the override' }).getAttribute('aria-disabled'),
        ).toBeNull()
        listed = undefined
        fireEvent.click(within(menu).getByRole('menuitem', { name: 'Read again' }))
        const items = await within(menu).findAllByRole('menuitemradio')
        expect(items.map((item) => item.textContent)).toEqual(LISTED)
        expect(within(menu).queryByText(/Could not read its models/u)).toBeNull()
        expect(sent.map((s) => s.path)).toEqual(['/api/models', '/api/models'])
    })

    it('shows a model the runtime no longer lists checked but not offered, its trigger marked', async () => {
        renderModels([{ agent: 'worker', model: 'acme/gone-1', source: 'ticket', variant: null }])
        // Nothing is known gone until the list is read.
        expect(screen.getByRole('button', { name: 'worker model: acme/gone-1' })).toBeDefined()
        const menu = openMenu('worker model: acme/gone-1')
        const items = await within(menu).findAllByRole('menuitemradio')
        expect(
            items.map((item) => [
                item.textContent,
                item.getAttribute('aria-checked'),
                item.getAttribute('aria-disabled'),
            ]),
        ).toEqual([
            ['acme/fast-1', 'false', null],
            ['acme/deep-2', 'false', null],
            ['acme/gone-1: no longer listed; its next run is refused', 'true', 'true'],
        ])
        // The menu hides the rest of the page from a screen reader while it is open.
        expect(
            screen.getByRole('button', {
                name: 'worker model: acme/gone-1, no longer listed; its next run is refused',
                hidden: true,
            }),
        ).toBeDefined()
    })

    it("offers config's model at a variant as the model alone, since an override names no variant", async () => {
        renderModels([{ agent: 'planner', model: 'acme/fast-1@high', source: 'config', variant: 'high' }])
        const menu = openMenu('planner model: acme/fast-1@high')
        const items = await within(menu).findAllByRole('menuitemradio')
        expect(items.map((item) => [item.textContent, item.getAttribute('aria-disabled')])).toEqual([
            ['acme/fast-1', null],
            ['acme/deep-2', null],
            ["acme/fast-1@high: config's, with a variant", 'true'],
        ])
        // Its model is listed, so its next run goes ahead: the trigger is not marked.
        expect(screen.getByRole('button', { name: 'planner model: acme/fast-1@high', hidden: true })).toBeDefined()
    })

    it('shows the model being saved on its button, marked pending, until the server answers', async () => {
        // The server's answer, held until the test gives it.
        const replies: ((response: Response) => void)[] = []
        answer = new Promise((resolve) => {
            replies.push(resolve)
        })
        renderModels()
        const menu = openMenu("reviewer model: the runtime's default")
        fireEvent.click(await within(menu).findByRole('menuitemradio', { name: 'acme/deep-2' }))
        const pending = await screen.findByRole('button', { name: 'reviewer model: acme/deep-2…' })
        expect(pending.getAttribute('aria-busy')).toBe('true')
        expect(screen.getByRole('button', { name: 'worker model: acme/deep-2' }).hasAttribute('disabled')).toBe(true)
        replies[0]?.(Response.json({ agent: 'reviewer', model: 'acme/deep-2', source: 'ticket', variant: null }))
        expect(
            await screen.findByText(
                "ABC-1's reviewer runs use acme/deep-2 from their next run: this ticket's override.",
            ),
        ).toBeDefined()
        expect(
            screen.getByRole('button', { name: "reviewer model: the runtime's default" }).getAttribute('aria-busy'),
        ).toBe('false')
    })

    it('names the agent and the guard of a refusal', async () => {
        answer = Response.json(
            { detail: { guard: 'unknown_model', reason: 'OpenCode does not list the model acme/fast-1' } },
            { status: 409 },
        )
        renderModels()
        const menu = openMenu("reviewer model: the runtime's default")
        fireEvent.click(await within(menu).findByRole('menuitemradio', { name: 'acme/fast-1' }))
        expect((await screen.findByRole('alert')).textContent).toBe(
            'reviewer: refused (unknown_model): OpenCode does not list the model acme/fast-1',
        )
    })

    it('shows nothing for a ticket the server sent no models for', () => {
        const { container } = renderModels([])
        expect(container.childElementCount).toBe(0)
    })
})
