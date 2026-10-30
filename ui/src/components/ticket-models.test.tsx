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
    dropped_variant: null,
    last_served: 'acme/deep-2',
}
const PLANNER: AgentModel = {
    agent: 'planner',
    model: 'acme/fast-1',
    source: 'config',
    variant: null,
    dropped_variant: null,
    last_served: 'acme/old-0',
}
const MODELS: AgentModel[] = [
    WORKER,
    PLANNER,
    {
        agent: 'reviewer',
        model: null,
        source: 'default',
        variant: null,
        dropped_variant: null,
        last_served: 'acme/fast-1',
    },
]
/** Each listed model's variants, as the server sends them, in the runtime's order: acme/fast-1 has none. */
const VARIANTS = { 'acme/deep-2': ['low', 'high'] }
/** The planner on config's acme/deep-2 at its `high` variant. */
const AT_HIGH: AgentModel = {
    agent: 'planner',
    model: 'acme/deep-2@high',
    source: 'config',
    variant: 'high',
    dropped_variant: null,
    last_served: 'acme/deep-2',
}
/** The server's answer to the reviewer's choice of acme/deep-2. */
const CHOSEN: AgentModel = {
    agent: 'reviewer',
    model: 'acme/deep-2',
    source: 'ticket',
    variant: null,
    dropped_variant: null,
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
            return listed ?? Response.json({ models: LISTED, variants: {}, error: null })
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

/** The models the list offers, in order, under their providers: every option but the pinned one. */
async function offered(list: HTMLElement): Promise<HTMLElement[]> {
    // Once the runtime's list is read, or could not be.
    await waitFor(() => expect(within(list).queryByText(/^Reading the runtime/u)).toBeNull())
    // The pinned one is narrowed away too, when what is typed is not in it.
    const top = within(list).queryByRole('group', { name: 'Chosen now' })
    const options = within(list).getAllByRole('option')
    return options.filter((o) => !top?.contains(o) && o.textContent !== 'Read again')
}

/** The button below the list that clears the ticket's override. */
function clearButton(): HTMLElement {
    return screen.getByRole('button', { name: 'Clear the override' })
}

/** What an option says: its label, as a model's variant under it has, else its text. */
function said(o: HTMLElement): string | null {
    return o.getAttribute('aria-label') ?? o.textContent
}

/** What an option says, whether it is checked, and whether it is disabled. */
function readOption(o: HTMLElement): [string | null, string | null, string | null] {
    return [said(o), o.getAttribute('aria-checked'), o.getAttribute('aria-disabled')]
}

describe('TicketModels', () => {
    it('shows a row per agent: its next model, where it comes from, and what served it last', async () => {
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
        // The runtime's list, read once as the rows show for the models they name, whichever rows name one.
        await waitFor(() => expect(sent).toEqual([{ method: 'GET', path: '/api/models', body: null }]))
    })

    it("reads no list while every agent is on the runtime's default, which no list can take away", async () => {
        renderModels([{ ...WORKER, model: null, source: 'default' }])
        expect(sent).toEqual([])
        const list = openPicker('worker model: runtime default')
        expect((await offered(list)).map((o) => o.textContent)).toEqual(LISTED)
        expect(sent).toEqual([{ method: 'GET', path: '/api/models', body: null }])
    })

    it('offers the models the runtime lists and sets the override, as canopy model KEY MODEL --agent', async () => {
        renderModels()
        const list = openPicker('reviewer model: runtime default')
        // The field that narrows the list takes the focus, so the keys work from the trigger.
        expect(document.activeElement).toBe(field('reviewer'))
        expect((await offered(list)).map((o) => o.textContent)).toEqual(LISTED)
        // The default is pinned as a state, not a choice: nothing is checked while nothing sets a model.
        expect(readOption(pinned(list))).toEqual(['runtime defaultnothing sets one', 'false', 'true'])
        expect((await offered(list)).map((o) => o.getAttribute('aria-checked'))).toEqual(['false', 'false'])
        expect(clearButton().hasAttribute('disabled')).toBe(true)
        fireEvent.click(within(list).getByRole('option', { name: 'acme/deep-2' }))
        expect(screen.queryByRole('listbox')).toBeNull()
        // Confirmed in the agent's row, which shows the choice before the ticket is read again.
        expect((await screen.findByRole('status')).textContent).toBe(
            "saved: ABC-1's reviewer runs use acme/deep-2 from their next run: this ticket's override.",
        )
        const rows = screen.getAllByTestId('ticket-model')
        expect(rows.map((row) => within(row).queryByRole('status') !== null)).toEqual([false, false, true])
        // In place of where the model comes from, so the row grows no longer for it.
        expect(rows.at(-1)?.textContent).toMatch(/^acme\/deep-2saved: /u)
        // The focus back on the trigger the choice was made from, as it was before the list opened.
        expect(document.activeElement).toBe(screen.getByRole('button', { name: 'reviewer model: acme/deep-2' }))
        expect(sent).toEqual([
            { method: 'GET', path: '/api/models', body: null },
            { method: 'POST', path: '/api/tickets/ABC-1/models', body: { agent: 'reviewer', model: 'acme/deep-2' } },
        ])
    })

    it('groups a long list by provider and narrows it to the ids holding what is typed', async () => {
        listed = Response.json({ models: MANY, variants: {}, error: null })
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
        // Below the list, out of it, so in reach whatever is typed and however far the list scrolls.
        expect(list.contains(clearButton())).toBe(false)
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
        answer = Response.json({
            agent: 'worker',
            model: null,
            source: 'default',
            variant: null,
            dropped_variant: null,
            last_served: null,
        })
        renderModels()
        const list = openPicker('worker model: acme/deep-2')
        expect(readOption(pinned(list))).toEqual(["acme/deep-2this ticket's override", 'true', 'false'])
        expect((await offered(list)).map((o) => readOption(o))).toEqual([
            ['acme/fast-1', 'false', 'false'],
            ['acme/deep-2', 'true', 'false'],
        ])
        fireEvent.click(pinned(list))
        expect(screen.queryByRole('listbox')).toBeNull()
        expect(sent.map((s) => s.method)).toEqual(['GET'])

        openPicker('worker model: acme/deep-2')
        fireEvent.click(clearButton())
        // Said as a clear, not a choice, as canopy model --clear does.
        expect((await screen.findByRole('status')).textContent).toBe(
            "cleared: ABC-1's worker runs use the runtime's default from their next run: nothing sets one.",
        )
        expect(screen.getByRole('button', { name: 'worker model: runtime default' })).toBeDefined()
        expect(sent.at(-1)).toEqual({
            method: 'POST',
            path: '/api/tickets/ABC-1/models',
            body: { agent: 'worker', model: null },
        })
    })

    it('says in the failure color why the list could not be read, offers no model, and reads it again', async () => {
        listed = Response.json({ models: [], variants: {}, error: '`opencode models` exited 1' })
        renderModels()
        const list = openPicker('worker model: acme/deep-2')
        expect(await within(list).findByText('Could not read its models: `opencode models` exited 1')).toBeDefined()
        // Every choice would be refused `model_list_failed`: none is offered, but clearing needs no list.
        expect(await offered(list)).toEqual([])
        expect(clearButton().hasAttribute('disabled')).toBe(false)
        listed = undefined
        fireEvent.click(within(list).getByRole('option', { name: 'Read again' }))
        await within(list).findByRole('group', { name: 'acme' })
        expect((await offered(list)).map((o) => o.textContent)).toEqual(LISTED)
        expect(within(list).queryByText(/Could not read its models/u)).toBeNull()
        expect(sent.map((s) => s.path)).toEqual(['/api/models', '/api/models'])
    })

    it("says a read of the list that failed in a read's words, not a write's", async () => {
        listed = Response.json({}, { status: 500 })
        renderModels()
        const list = openPicker('worker model: acme/deep-2')
        expect(await within(list).findByText('Could not read its models: the server answered 500')).toBeDefined()
        // No model is known gone while the list is unread.
        expect(screen.getByRole('button', { name: 'worker model: acme/deep-2', hidden: true })).toBeDefined()
    })

    it('shows a model the runtime no longer lists checked but not offered, its trigger marked', async () => {
        renderModels([
            {
                agent: 'worker',
                model: 'acme/gone-1',
                source: 'ticket',
                variant: null,
                dropped_variant: null,
                last_served: null,
            },
        ])
        // Nothing is known gone until the list is read, which the row does as it shows, with no menu open.
        expect(screen.getByRole('button', { name: 'worker model: acme/gone-1' })).toBeDefined()
        const gone = 'worker model: acme/gone-1, no longer listed; its next run is refused'
        await screen.findByRole('button', { name: gone })
        const list = openPicker(gone)
        expect((await offered(list)).map((o) => readOption(o))).toEqual([
            ['acme/fast-1', 'false', 'false'],
            ['acme/deep-2', 'false', 'false'],
        ])
        // Checked, never offered, and why said under it rather than in its disabled text.
        expect(readOption(pinned(list))).toEqual(['acme/gone-1', 'true', 'true'])
        expect(
            within(list).getByRole('option', {
                name: 'acme/gone-1',
                description: 'no longer listed; its next run is refused',
            }),
        ).toBe(pinned(list))
        expect(sent).toEqual([{ method: 'GET', path: '/api/models', body: null }])
    })

    it("offers each model's variants under it, and sets the override to one, as canopy model does", async () => {
        listed = Response.json({ models: LISTED, variants: VARIANTS, error: null })
        answer = Response.json({ ...CHOSEN, model: 'acme/deep-2@high', variant: 'high' })
        renderModels()
        const list = openPicker('reviewer model: runtime default')
        const options = await offered(list)
        // In the runtime's order, the model at its default first.
        expect(options.map((o) => said(o))).toEqual([
            'acme/fast-1',
            'acme/deep-2 (default)',
            'acme/deep-2@low',
            'acme/deep-2@high',
        ])
        // Each variant under its model, which it names to the eye no more.
        expect(options.at(-1)?.textContent).toBe('@high')
        // What is typed finds a variant by its own id, and names its model with it, the model's row hidden.
        fireEvent.change(field('reviewer'), { target: { value: 'high' } })
        expect((await offered(list)).map((o) => [said(o), o.textContent])).toEqual([
            ['acme/deep-2@high', 'acme/deep-2@high'],
        ])
        fireEvent.click(within(list).getByRole('option', { name: 'acme/deep-2@high' }))
        expect((await screen.findByRole('status')).textContent).toBe(
            "saved: ABC-1's reviewer runs use acme/deep-2@high from their next run: this ticket's override.",
        )
        expect(sent.at(-1)).toEqual({
            method: 'POST',
            path: '/api/tickets/ABC-1/models',
            body: { agent: 'reviewer', model: 'acme/deep-2@high' },
        })
    })

    it('takes the first model at a variant typed when Enter is pressed, not a model at its default', async () => {
        const many = ['acme/deep-2', 'acme/deep-3', 'bravo/wide-1']
        listed = Response.json({
            models: many,
            variants: { 'acme/deep-2': ['low', 'high'], 'acme/deep-3': ['high'], 'bravo/wide-1': ['high'] },
            error: null,
        })
        answer = Response.json({ ...AT_HIGH, source: 'ticket' })
        // The planner on config's acme/deep-2 at high: what is typed passes the pinned model by.
        renderModels([AT_HIGH])
        const list = openPicker('planner model: acme/deep-2@high')
        await offered(list)
        fireEvent.change(field('planner'), { target: { value: 'high' } })
        expect((await offered(list)).map((o) => said(o))).toEqual([
            'acme/deep-2@high',
            'acme/deep-3@high',
            'bravo/wide-1@high',
        ])
        expect(within(list).queryByRole('group', { name: 'Chosen now' })).toBeNull()
        fireEvent.keyDown(field('planner'), { key: 'Enter' })
        expect((await screen.findByRole('status')).textContent).toMatch(/^saved: /u)
        expect(sent.at(-1)?.body).toEqual({ agent: 'planner', model: 'acme/deep-2@high' })
        // Opened again, the list is whole, the pinned model at its top.
        const again = openPicker('planner model: acme/deep-2@high')
        expect(field('planner')).toHaveProperty('value', '')
        expect(within(again).getByRole('group', { name: 'Chosen now' })).toBeDefined()
    })

    it("shows config's model at its variant, checked at that variant, and takes it whole as the override", async () => {
        listed = Response.json({ models: LISTED, variants: VARIANTS, error: null })
        answer = Response.json({ ...AT_HIGH, source: 'ticket' })
        renderModels([AT_HIGH])
        // What served it is the model alone, or at the variant, either of which its row names.
        expect(screen.getByTestId('ticket-model').textContent).toBe('acme/deep-2@high[runtime.models]')
        const list = openPicker('planner model: acme/deep-2@high')
        expect((await offered(list)).map((o) => readOption(o))).toEqual([
            ['acme/fast-1', 'false', 'false'],
            ['acme/deep-2 (default)', 'false', 'false'],
            ['acme/deep-2@low', 'false', 'false'],
            ['acme/deep-2@high', 'true', 'false'],
        ])
        expect(readOption(pinned(list))).toEqual(['acme/deep-2@high[runtime.models]', 'true', 'false'])
        fireEvent.click(pinned(list))
        expect((await screen.findByRole('status')).textContent).toBe(
            "saved: ABC-1's planner runs use acme/deep-2@high from their next run: this ticket's override.",
        )
        expect(sent.at(-1)?.body).toEqual({ agent: 'planner', model: 'acme/deep-2@high' })
    })

    it("says an override naming no variant sets config's aside, as canopy model does", async () => {
        listed = Response.json({ models: LISTED, variants: VARIANTS, error: null })
        answer = Response.json({
            ...AT_HIGH,
            model: 'acme/deep-2',
            source: 'ticket',
            variant: null,
            dropped_variant: 'high',
        })
        renderModels([AT_HIGH])
        const list = openPicker('planner model: acme/deep-2@high')
        fireEvent.click(await within(list).findByRole('option', { name: 'acme/deep-2 (default)' }))
        const status = await screen.findByRole('status')
        expect(within(status).getByText("ABC-1's", { exact: false }).textContent).toBe(
            ": ABC-1's planner runs use acme/deep-2 from their next run: this ticket's override (config's variant " +
                '`high` no longer applies).',
        )
        // Said to the eye too, beside `saved`.
        expect(status.textContent).toMatch(/\(config's variant high no longer applies\)$/u)
    })

    it('marks a variant the runtime no longer lists for its model, as a model no longer listed', async () => {
        listed = Response.json({ models: LISTED, variants: { 'acme/deep-2': ['low'] }, error: null })
        renderModels([AT_HIGH])
        const gone = 'planner model: acme/deep-2@high, variant no longer listed; its next run is refused'
        await screen.findByRole('button', { name: gone })
        const list = openPicker(gone)
        await offered(list)
        expect(readOption(pinned(list))).toEqual(['acme/deep-2@high', 'true', 'true'])
        expect(within(list).getByText('variant no longer listed; its next run is refused')).toBeDefined()
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
        // Still focusable, so the focus the list hands back stays on it, but it opens nothing until the save is done.
        expect(pending.getAttribute('aria-disabled')).toBe('true')
        expect(pending.hasAttribute('disabled')).toBe(false)
        expect(document.activeElement).toBe(pending)
        fireEvent.click(pending)
        expect(screen.queryByRole('listbox')).toBeNull()
        replies[0]?.(Response.json(CHOSEN))
        expect(await screen.findByRole('status')).toBeDefined()
        const saved = screen.getByRole('button', { name: 'reviewer model: acme/deep-2' })
        expect([saved.getAttribute('aria-busy'), saved.getAttribute('aria-disabled')]).toEqual(['false', 'false'])
    })

    it('names the guard of a refusal in the row of the agent it refused', async () => {
        answer = Response.json(
            { detail: { guard: 'unknown_model', reason: 'OpenCode does not list the model acme/fast-1' } },
            { status: 409 },
        )
        renderModels()
        const list = openPicker('reviewer model: runtime default')
        fireEvent.click(await within(list).findByRole('option', { name: 'acme/fast-1' }))
        const alert = await screen.findByRole('alert')
        expect(alert.textContent).toBe('refused (unknown_model): OpenCode does not list the model acme/fast-1')
        expect(screen.getAllByRole('definition').map((row) => row.contains(alert))).toEqual([false, false, true])
    })

    it('names a long id whole on hover, which its trigger and the list end in an ellipsis', async () => {
        const long = 'openrouter/anthropic/claude-opus-4.1-20250805-preview'
        listed = Response.json({ models: [long], variants: { [long]: ['high'] }, error: null })
        renderModels([{ ...AT_HIGH, model: `${long}@high` }])
        const trigger = screen.getByRole('button', { name: `planner model: ${long}@high` })
        expect(trigger.getAttribute('title')).toBe(`${long}@high`)
        const list = openPicker(`planner model: ${long}@high`)
        expect(pinned(list).getAttribute('title')).toBe(`${long}@high`)
        expect((await offered(list)).map((o) => o.getAttribute('title'))).toEqual([long, `${long}@high`])
    })

    it('shows nothing for a ticket the server sent no models for', () => {
        const { container } = renderModels([])
        expect(container.childElementCount).toBe(0)
    })
})
