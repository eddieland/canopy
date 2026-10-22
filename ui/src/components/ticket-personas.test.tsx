import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import type { AgentPersona, PersonaList } from '@/api/types'

import { TicketPersonas } from './ticket-personas'

const NAMES = ['canopy', 'explainer', 'minimalist', 'skeptic']
const PERSONAS: AgentPersona[] = [
    { agent: 'worker', persona: 'minimalist', source: 'ticket', error: null, once: null, several: [] },
    { agent: 'planner', persona: 'skeptic', source: 'config', error: null, once: null, several: [] },
    { agent: 'reviewer', persona: 'canopy', source: 'default', error: null, once: null, several: [] },
]
// What the menus describe each persona with: skeptic alone has a description here.
const SKEPTIC = 'When you review, name the input that breaks a claim.'
const LISTED: PersonaList = {
    reviewer: 'canopy',
    personas: NAMES.map((name) => ({
        name,
        yours: false,
        defaults: [],
        error: null,
        description: name === 'skeptic' ? SKEPTIC : null,
    })),
}

// Every choice the menus send, and what the server stand-in answers each.
let sent: { path: string; body: unknown }[] = []
let answer: Response | undefined

const server: Middleware = {
    async onRequest({ request }) {
        // The personas the menus describe: a read, not one of the choices a test counts.
        if (new URL(request.url).pathname === '/api/personas') {
            return Response.json(LISTED)
        }
        sent.push({ path: new URL(request.url).pathname, body: JSON.parse(await request.text()) as unknown })
        return (
            answer ??
            Response.json({
                agent: 'reviewer',
                persona: 'skeptic',
                source: 'ticket',
                error: null,
                once: null,
                several: [],
            })
        )
    },
}

beforeEach(() => {
    sent = []
    answer = undefined
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

function renderPersonas(personas: AgentPersona[] = PERSONAS) {
    return render(
        <QueryClientProvider client={new QueryClient()}>
            <TicketPersonas ticketKey="ABC-1" personas={personas} names={NAMES} />
        </QueryClientProvider>,
    )
}

function openMenu(name: string) {
    fireEvent.pointerDown(screen.getByRole('button', { name }), { button: 0, ctrlKey: false })
    return screen.getByRole('menu')
}

describe('TicketPersonas', () => {
    it("shows each agent's next persona and where it comes from, in the CLI's words", () => {
        renderPersonas()
        const rows = screen.getAllByRole('definition').map((row) => row.textContent)
        expect(rows).toEqual(["minimalistthis ticket's override", 'skeptic[personas]', "canopycanopy's default"])
    })

    it("names the persona chosen for an agent's next run alone under its row", () => {
        renderPersonas([
            { agent: 'worker', persona: 'canopy', source: 'default', error: null, once: 'skeptic', several: [] },
        ])
        expect(screen.getByRole('definition').textContent).toBe("canopycanopy's defaultIts next run alone: skeptic")
    })

    it("names each persona the reviewer's PRs are reviewed in, one review each", () => {
        renderPersonas([
            {
                agent: 'reviewer',
                persona: 'canopy',
                source: 'default',
                error: null,
                once: null,
                several: ['skeptic', 'explainer'],
            },
        ])
        expect(screen.getByRole('definition').textContent).toBe(
            "canopycanopy's defaultOne review each in: skeptic, explainer",
        )
    })

    it('sets the override from the menu, as canopy persona KEY NAME --agent does, and says what it did', async () => {
        renderPersonas()
        const menu = openMenu('reviewer persona: canopy')
        const items = within(menu).getAllByRole('menuitemradio')
        expect(items).toEqual(NAMES.map((name) => within(menu).getByRole('menuitemradio', { name })))
        // Each says what it is under its name, as the review request's menu does, apart from its name.
        expect(await within(menu).findByRole('menuitemradio', { name: 'skeptic', description: SKEPTIC })).toBe(items[3])
        // Nothing is checked while no override stands: the agent's persona is config's, not the ticket's.
        expect(items.map((item) => item.getAttribute('aria-checked'))).toEqual(['false', 'false', 'false', 'false'])
        expect(within(menu).getByRole('menuitem', { name: 'Clear the override' }).getAttribute('aria-disabled')).toBe(
            'true',
        )
        fireEvent.click(within(menu).getByRole('menuitemradio', { name: 'skeptic' }))
        expect(
            await screen.findByText(
                "ABC-1's reviewer runs write in skeptic from their next run: this ticket's override.",
            ),
        ).toBeDefined()
        expect(sent).toEqual([{ path: '/api/tickets/ABC-1/personas', body: { agent: 'reviewer', persona: 'skeptic' } }])
    })

    it('clears an override standing, as --clear does', async () => {
        answer = Response.json({
            agent: 'worker',
            persona: 'canopy',
            source: 'default',
            error: null,
            once: null,
            several: [],
        })
        renderPersonas()
        const menu = openMenu('worker persona: minimalist')
        expect(within(menu).getByRole('menuitemradio', { name: 'minimalist' }).getAttribute('aria-checked')).toBe(
            'true',
        )
        fireEvent.click(within(menu).getByRole('menuitem', { name: 'Clear the override' }))
        expect(
            await screen.findByText("ABC-1's worker runs write in canopy from their next run: canopy's default."),
        ).toBeDefined()
        expect(sent).toEqual([{ path: '/api/tickets/ABC-1/personas', body: { agent: 'worker', persona: null } }])
    })

    it('names the guard of a refusal, and says why a run would refuse its persona', async () => {
        answer = Response.json(
            { detail: { guard: 'unknown_persona', reason: 'persona gone has no file' } },
            { status: 409 },
        )
        renderPersonas([
            {
                agent: 'worker',
                persona: 'gone',
                source: 'ticket',
                error: 'persona gone has no file',
                once: null,
                several: [],
            },
        ])
        expect(screen.getByText('Its next run is refused: persona gone has no file')).toBeDefined()
        // The persona chosen stays in the menu, checked, though its file has gone.
        const menu = openMenu('worker persona: gone')
        expect(within(menu).getByRole('menuitemradio', { name: 'gone' }).getAttribute('aria-checked')).toBe('true')
        fireEvent.click(within(menu).getByRole('menuitemradio', { name: 'skeptic' }))
        expect((await screen.findByRole('alert')).textContent).toBe(
            'refused (unknown_persona): persona gone has no file',
        )
    })

    it('shows nothing for a ticket the server sent no personas for', () => {
        const { container } = renderPersonas([])
        expect(container.childElementCount).toBe(0)
    })
})
