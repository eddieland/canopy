import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import type { AgentModel } from '@/api/types'

import { TicketModels } from './ticket-models'

const LISTED = ['acme/fast-1', 'acme/deep-2']
// About what a runtime with a few gateways lists: two hundred ids across four providers.
const PROVIDERS = ['acme', 'bravo', 'charlie', 'delta']
const MANY = PROVIDERS.flatMap((provider) =>
    Array.from({ length: 50 }, (_, i) => `${provider}/model-${String(i).padStart(2, '0')}`),
)
const WORKER: AgentModel = {
    agent: 'worker',
    model: 'acme/deep-2',
    source: 'ticket',
    variant: null,
    last_served: 'acme/deep-2',
}
const PLANNER: AgentModel = {
    agent: 'planner',
    model: 'acme/fast-1',
    source: 'config',
    variant: null,
    last_served: 'acme/old-0',
}
const MODELS: AgentModel[] = [
    WORKER,
    PLANNER,
    { agent: 'reviewer', model: null, source: 'default', variant: null, last_served: 'acme/fast-1' },
]
/** The server's answer to the reviewer's choice of acme/deep-2. */
const CHOSEN: AgentModel = {
    agent: 'reviewer',
    model: 'acme/deep-2',
    source: 'ticket',
    variant: null,
    last_served: 'acme/fast-1',
}

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
        return answer ?? Response.json(CHOSEN)
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
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const page = (now: AgentModel[]) => (
        <QueryClientProvider client={client}>
            <TicketModels ticketKey="ABC-1" models={now} />
        </QueryClientProvider>
    )
    const rendered = render(page(models))
    // The ticket read again, as the stream has it once something changes.
    return { ...rendered, reads: (now: AgentModel[]) => rendered.rerender(page(now)) }
}

/** Opens an agent's picker, as a click or Enter on its trigger does, and gives its list. */
function openPicker(name: string): HTMLElement {
    fireEvent.click(screen.getByRole('button', { name }))
    return screen.getByRole('listbox', { name: 'Models' })
}

/** The field that narrows an agent's list. */
function field(agent: string): HTMLElement {
    return screen.getByRole('combobox', { name: `Find a model for the ${agent}` })
}

/** The option pinned at the top of the list: the model chosen now. */
function pinned(list: HTMLElement): HTMLElement {
    return within(within(list).getByRole('group', { name: 'Chosen now' })).getByRole('option')
}

/** The models the list offers, in order, under their providers: every option but the pinned one and the foot. */
async function offered(list: HTMLElement): Promise<HTMLElement[]> {
    // Once the runtime's list is read, or could not be.
    await waitFor(() => expect(within(list).queryByText(/^Reading the runtime/u)).toBeNull())
    // The pinned one is narrowed away too, when what is typed is not in it.
    const top = within(list).queryByRole('group', { name: 'Chosen now' })
    const options = within(list).getAllByRole('option')
    return options.filter((o) => !top?.contains(o) && !['Clear the override', 'Read again'].includes(o.textContent))
}

/** What an option says, whether it is checked, and whether it is disabled. */
function readOption(o: HTMLElement): [string | null, string | null, string | null] {
    return [o.textContent, o.getAttribute('aria-checked'), o.getAttribute('aria-disabled')]
}

describe('TicketModels', () => {
    it('shows a row per agent: its next model, where it comes from, and what served it last, reading no list', () => {
        renderModels()
        expect(screen.getAllByRole('term').map((label) => label.textContent)).toEqual([
            'worker model',
            'planner model',
            'reviewer model',
        ])
        // What last served an agent is named only when it is not the model the row names.
        expect(screen.getAllByTestId('ticket-model').map((row) => row.textContent)).toEqual([
            "acme/deep-2this ticket's override",
            'acme/fast-1[runtime.models]last served acme/old-0',
            'runtime defaultlast served acme/fast-1',
        ])
        expect(sent).toEqual([])
    })

    it('reads the models when a picker opens and sets the override, as canopy model KEY MODEL --agent', async () => {
        renderModels()
        const list = openPicker('reviewer model: runtime default')
        // The field that narrows the list takes the focus, so the keys work from the trigger.
        expect(document.activeElement).toBe(field('reviewer'))
        expect((await offered(list)).map((o) => o.textContent)).toEqual(LISTED)
        // The default is pinned as a state, not a choice: nothing is checked while nothing sets a model.
        expect(readOption(pinned(list))).toEqual(['runtime defaultnothing sets one', 'false', 'true'])
        expect((await offered(list)).map((o) => o.getAttribute('aria-checked'))).toEqual(['false', 'false'])
        expect(within(list).getByRole('option', { name: 'Clear the override' }).getAttribute('aria-disabled')).toBe(
            'true',
        )
        fireEvent.click(within(list).getByRole('option', { name: 'acme/deep-2' }))
        expect(screen.queryByRole('listbox')).toBeNull()
        // Confirmed in the agent's row, which shows the choice before the ticket is read again.
        expect((await screen.findByRole('status')).textContent).toBe(
            "saved: ABC-1's reviewer runs use acme/deep-2 from their next run: this ticket's override.",
        )
        const rows = screen.getAllByTestId('ticket-model')
        expect(rows.map((row) => within(row).queryByRole('status') !== null)).toEqual([false, false, true])
        expect(rows.at(-1)?.textContent).toMatch(/^acme\/deep-2this ticket's overridesaved: /u)
        expect(sent).toEqual([
            { method: 'GET', path: '/api/models', body: null },
            { method: 'POST', path: '/api/tickets/ABC-1/models', body: { agent: 'reviewer', model: 'acme/deep-2' } },
        ])
    })

    it('groups a long list by provider and narrows it to the ids holding what is typed', async () => {
        listed = Response.json({ models: MANY, error: null })
        renderModels()
        const list = openPicker('reviewer model: runtime default')
        expect(await offered(list)).toHaveLength(200)
        expect(
            PROVIDERS.map((p) => within(within(list).getByRole('group', { name: p })).getAllByRole('option').length),
        ).toEqual([50, 50, 50, 50])
        fireEvent.change(field('reviewer'), { target: { value: 'lie/model-4' } })
        expect((await offered(list)).map((o) => o.textContent)).toEqual(
            Array.from({ length: 10 }, (_, i) => `charlie/model-4${i}`),
        )
        expect(within(list).queryByRole('group', { name: 'acme' })).toBeNull()
        // The foot stays in reach whatever is typed.
        expect(within(list).getByRole('option', { name: 'Clear the override' })).toBeDefined()
        fireEvent.change(field('reviewer'), { target: { value: 'nope' } })
        expect(within(list).getByText('no model has that name')).toBeDefined()
    })

    it('picks a model with the keys alone, from the trigger', async () => {
        renderModels()
        const list = openPicker('reviewer model: runtime default')
        await offered(list)
        // Past the pinned default, which is no choice, to the first model listed, then the next.
        fireEvent.keyDown(field('reviewer'), { key: 'ArrowDown' })
        fireEvent.keyDown(field('reviewer'), { key: 'ArrowDown' })
        fireEvent.keyDown(field('reviewer'), { key: 'Enter' })
        expect(screen.queryByRole('listbox')).toBeNull()
        expect((await screen.findByRole('status')).textContent).toBe(
            "saved: ABC-1's reviewer runs use acme/deep-2 from their next run: this ticket's override.",
        )
        expect(sent.at(-1)).toEqual({
            method: 'POST',
            path: '/api/tickets/ABC-1/models',
            body: { agent: 'reviewer', model: 'acme/deep-2' },
        })
    })

    it("marks config's model as chosen, pinned and in its provider's group, and takes it as the override", async () => {
        answer = Response.json({ ...PLANNER, source: 'ticket' })
        renderModels()
        const list = openPicker('planner model: acme/fast-1')
        expect(readOption(pinned(list))).toEqual(['acme/fast-1[runtime.models]', 'true', 'false'])
        expect((await offered(list)).map((o) => readOption(o))).toEqual([
            ['acme/fast-1', 'true', 'false'],
            ['acme/deep-2', 'false', 'false'],
        ])
        // Pinning config's model as the ticket's own is a choice, so the pinned item makes it.
        fireEvent.click(pinned(list))
        expect((await screen.findByRole('status')).textContent).toBe(
            "saved: ABC-1's planner runs use acme/fast-1 from their next run: this ticket's override.",
        )
    })

    it('stays confirmed while a read brings the choice in, and goes once the models change after it', async () => {
        const { reads } = renderModels()
        const list = openPicker('reviewer model: runtime default')
        fireEvent.click(await within(list).findByRole('option', { name: 'acme/deep-2' }))
        expect(await screen.findByRole('status')).toBeDefined()
        reads([WORKER, PLANNER, CHOSEN])
        expect(screen.getByRole('status')).toBeDefined()
        // The same models, read again.
        reads([WORKER, PLANNER, CHOSEN])
        expect(screen.getByRole('status')).toBeDefined()
        reads([WORKER, PLANNER, { ...CHOSEN, last_served: 'acme/deep-2' }])
        expect(screen.queryByRole('status')).toBeNull()
        expect(screen.getByRole('button', { name: 'reviewer model: acme/deep-2' })).toBeDefined()
    })

    it('clears an override standing, as --clear does, and saves nothing for the override chosen again', async () => {
        answer = Response.json({ agent: 'worker', model: null, source: 'default', variant: null, last_served: null })
        renderModels()
        let list = openPicker('worker model: acme/deep-2')
        expect(readOption(pinned(list))).toEqual(["acme/deep-2this ticket's override", 'true', 'false'])
        expect((await offered(list)).map((o) => readOption(o))).toEqual([
            ['acme/fast-1', 'false', 'false'],
            ['acme/deep-2', 'true', 'false'],
        ])
        fireEvent.click(pinned(list))
        expect(screen.queryByRole('listbox')).toBeNull()
        expect(sent.map((s) => s.method)).toEqual(['GET'])

        list = openPicker('worker model: acme/deep-2')
        fireEvent.click(within(list).getByRole('option', { name: 'Clear the override' }))
        expect((await screen.findByRole('status')).textContent).toBe(
            "saved: ABC-1's worker runs use the runtime's default from their next run: nothing sets one.",
        )
        expect(screen.getByRole('button', { name: 'worker model: runtime default' })).toBeDefined()
        expect(sent.at(-1)).toEqual({
            method: 'POST',
            path: '/api/tickets/ABC-1/models',
            body: { agent: 'worker', model: null },
        })
    })

    it('says in the failure color why the list could not be read, offers no model, and reads it again', async () => {
        listed = Response.json({ models: [], error: '`opencode models` exited 1' })
        renderModels()
        const list = openPicker('worker model: acme/deep-2')
        expect(await within(list).findByText('Could not read its models: `opencode models` exited 1')).toBeDefined()
        // Every choice would be refused `model_list_failed`: none is offered, but clearing needs no list.
        expect(await offered(list)).toEqual([])
        expect(within(list).getByRole('option', { name: 'Clear the override' }).getAttribute('aria-disabled')).toBe(
            'false',
        )
        listed = undefined
        fireEvent.click(within(list).getByRole('option', { name: 'Read again' }))
        await within(list).findByRole('group', { name: 'acme' })
        expect((await offered(list)).map((o) => o.textContent)).toEqual(LISTED)
        expect(within(list).queryByText(/Could not read its models/u)).toBeNull()
        expect(sent.map((s) => s.path)).toEqual(['/api/models', '/api/models'])
    })

    it('shows a model the runtime no longer lists checked but not offered, its trigger marked', async () => {
        renderModels([{ agent: 'worker', model: 'acme/gone-1', source: 'ticket', variant: null, last_served: null }])
        // Nothing is known gone until the list is read.
        expect(screen.getByRole('button', { name: 'worker model: acme/gone-1' })).toBeDefined()
        const list = openPicker('worker model: acme/gone-1')
        expect((await offered(list)).map((o) => readOption(o))).toEqual([
            ['acme/fast-1', 'false', 'false'],
            ['acme/deep-2', 'false', 'false'],
        ])
        expect(readOption(pinned(list))).toEqual([
            'acme/gone-1no longer listed; its next run is refused',
            'true',
            'true',
        ])
        // The list hides the rest of the page from a screen reader while it is open.
        expect(
            screen.getByRole('button', {
                name: 'worker model: acme/gone-1, no longer listed; its next run is refused',
                hidden: true,
            }),
        ).toBeDefined()
    })

    it("offers config's model at a variant as the model alone, since an override names no variant", async () => {
        renderModels([
            {
                agent: 'planner',
                model: 'acme/fast-1@high',
                source: 'config',
                variant: 'high',
                last_served: 'acme/fast-1',
            },
        ])
        // What served it is the model alone, which is the one its row names.
        expect(screen.getByTestId('ticket-model').textContent).toBe('acme/fast-1@high[runtime.models]')
        const list = openPicker('planner model: acme/fast-1@high')
        expect((await offered(list)).map((o) => readOption(o))).toEqual([
            ['acme/fast-1', 'true', 'false'],
            ['acme/deep-2', 'false', 'false'],
        ])
        expect(readOption(pinned(list))).toEqual(["acme/fast-1@highconfig's, with a variant", 'true', 'true'])
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
        const list = openPicker('reviewer model: runtime default')
        fireEvent.click(await within(list).findByRole('option', { name: 'acme/deep-2' }))
        const pending = await screen.findByRole('button', { name: 'reviewer model: acme/deep-2…' })
        expect(pending.getAttribute('aria-busy')).toBe('true')
        expect(screen.getByRole('button', { name: 'worker model: acme/deep-2' }).hasAttribute('disabled')).toBe(true)
        replies[0]?.(Response.json(CHOSEN))
        expect(await screen.findByRole('status')).toBeDefined()
        expect(screen.getByRole('button', { name: 'reviewer model: acme/deep-2' }).getAttribute('aria-busy')).toBe(
            'false',
        )
    })

    it('names the agent and the guard of a refusal', async () => {
        answer = Response.json(
            { detail: { guard: 'unknown_model', reason: 'OpenCode does not list the model acme/fast-1' } },
            { status: 409 },
        )
        renderModels()
        const list = openPicker('reviewer model: runtime default')
        fireEvent.click(await within(list).findByRole('option', { name: 'acme/fast-1' }))
        expect((await screen.findByRole('alert')).textContent).toBe(
            'reviewer: refused (unknown_model): OpenCode does not list the model acme/fast-1',
        )
    })

    it('shows nothing for a ticket the server sent no models for', () => {
        const { container } = renderModels([])
        expect(container.childElementCount).toBe(0)
    })
})
