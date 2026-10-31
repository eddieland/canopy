import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import type { ConfigModels, ConfigSettings, ModelList, PersonaList } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { StartTicket } from './start-ticket'

// canopy's persona, every agent's default but the reviewer's, which `[personas] reviewers` gives two of.
const PERSONAS: PersonaList = {
    reviewer: 'canopy',
    personas: [
        { name: 'canopy', yours: false, defaults: ['worker', 'planner'], error: null, description: null },
        { name: 'skeptic', yours: false, defaults: ['reviewer'], error: null, description: 'Name the input.' },
        { name: 'minimalist', yours: false, defaults: ['reviewer'], error: null, description: null },
    ],
}
// Config's worker on acme/fast-1, and the models the runtime lists: acme/deep-2 at two variants.
const CONFIG: ConfigModels = {
    agents: [{ agent: 'worker', model: 'acme/fast-1', variant: null, source: 'config' }],
    chores: [],
    models_file: '/home/me/.config/canopy/config.toml',
    chores_file: null,
    user_file: '/home/me/.config/canopy/config.toml',
    private_file: '/home/me/.config/canopy/private.toml',
}
const LISTED: ModelList = {
    models: ['acme/fast-1', 'acme/deep-2'],
    variants: { 'acme/deep-2': ['low', 'high'] },
    error: null,
}

// The settings as `policy.plan` is set: `off`, or `approve` once a test sets it.
function settings(plan: 'off' | 'approve'): ConfigSettings {
    return {
        keys: [
            {
                name: 'policy.plan',
                value: plan,
                source: 'default',
                kind: 'stricter',
                bound: null,
                looser: null,
                choices: ['off', 'approve'],
            },
        ],
        private_file: '/home/me/.config/canopy/private.toml',
        user_file: '/home/me/.config/canopy/config.toml',
        workspace_file: '/repo/canopy.toml',
        hash: '0',
        repos: ['repo'],
        every: null,
    }
}
let policy: 'off' | 'approve' = 'off'

// Every path the form posts to, the bodies sent, and what the server stand-in answers.
let sent: string[] = []
let bodies: unknown[] = []
let answer: Response | undefined
// What the menus read, apart from what the form sends.
let reads: string[] = []

const server: Middleware = {
    async onRequest({ request }) {
        const url = new URL(request.url)
        const read = {
            '/api/personas': PERSONAS,
            '/api/config/models': CONFIG,
            '/api/models': LISTED,
            '/api/config': settings(policy),
        }[url.pathname]
        if (read !== undefined) {
            reads.push(url.pathname)
            return Response.json(read)
        }
        sent.push(url.pathname)
        const body = await request.text()
        if (body !== '') {
            bodies.push(JSON.parse(body))
        }
        return answer ?? Response.json({ already: false, running_run: null, running_private: null })
    },
}

beforeEach(() => {
    sent = []
    bodies = []
    reads = []
    policy = 'off'
    answer = undefined
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

function start(key: string) {
    fireEvent.change(screen.getByRole('textbox', { name: 'Ticket key' }), { target: { value: key } })
    fireEvent.submit(screen.getByRole('form', { name: 'Start a ticket' }))
}

function showOverrides() {
    fireEvent.click(screen.getByRole('button', { name: 'Show persona and model overrides' }))
}

async function openPersonas(name: string) {
    const trigger = await screen.findByRole<HTMLButtonElement>('button', { name })
    await expect.poll(() => trigger.disabled).toBe(false)
    fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false })
    return screen.getByRole('menu')
}

async function openModels(name: string) {
    fireEvent.click(await screen.findByRole('button', { name }))
    const list = screen.getByRole('listbox', { name: 'Models' })
    await within(list).findByRole('group', { name: 'acme' })
    return list
}

describe('StartTicket', () => {
    it('says up front that it needs no queue label and keeps the conversation in canopy', async () => {
        await renderRouted(<StartTicket />)
        expect(screen.getByRole('status').textContent).toBe(
            'No queue label needed. Its conversation stays in canopy: nothing reaches the ticket.',
        )
    })

    it('starts the ticket by its key as typed, trimmed, then opens its page', async () => {
        const { router } = await renderRouted(<StartTicket />, { at: '/tickets' })
        start('  ABC-1 ')
        await waitFor(() => {
            expect(router.state.location.pathname).toBe('/tickets/ABC-1')
        })
        expect(sent).toEqual(['/api/tickets/ABC-1/start'])
        // It picks nothing, so it sets none of the ticket's overrides, and the menus, never shown, read nothing.
        expect(bodies).toEqual([{ personas: [], models: [], plan: null }])
        expect(reads).toEqual(['/api/config'])
    })

    it('asks for a plan the policy would not, as canopy start --plan does', async () => {
        await renderRouted(<StartTicket />)
        const plan = screen.getByRole('checkbox', { name: 'Plan it first' })
        await waitFor(() => {
            expect(reads).toContain('/api/config')
        })
        expect(plan.getAttribute('aria-checked')).toBe('false')
        expect(screen.queryByText('policy.plan')).toBeNull()
        fireEvent.click(plan)
        expect(plan.getAttribute('aria-checked')).toBe('true')
        start('ABC-1')
        await waitFor(() => {
            expect(bodies).toEqual([{ personas: [], models: [], plan: true }])
        })
    })

    it("is checked when Settings' policy.plan is approve, says so, and waives the plan once unchecked", async () => {
        policy = 'approve'
        await renderRouted(<StartTicket />)
        const plan = screen.getByRole('checkbox', { name: 'Plan it first' })
        await waitFor(() => {
            expect(plan.getAttribute('aria-checked')).toBe('true')
        })
        expect(screen.getByText('policy.plan')).toBeTruthy()
        fireEvent.click(plan)
        expect(plan.getAttribute('aria-checked')).toBe('false')
        expect(screen.queryByText('policy.plan')).toBeNull()
        start('ABC-1')
        await waitFor(() => {
            expect(bodies).toEqual([{ personas: [], models: [], plan: false }])
        })
    })

    it("leaves the ticket's own setting alone while the box agrees with policy.plan", async () => {
        policy = 'approve'
        await renderRouted(<StartTicket />)
        await waitFor(() => {
            expect(screen.getByRole('checkbox', { name: 'Plan it first' }).getAttribute('aria-checked')).toBe('true')
        })
        start('ABC-1')
        await waitFor(() => {
            expect(bodies).toEqual([{ personas: [], models: [], plan: null }])
        })
    })

    it("shows each agent's persona and model, in the order a ticket meets them, each naming its default", async () => {
        await renderRouted(<StartTicket />)
        showOverrides()
        const group = screen.getByRole('group', { name: 'Persona and model overrides' })
        // `[personas] reviewers` names two, one review each, once the personas are read.
        expect(
            await within(group).findByRole('button', { name: 'reviewer persona: skeptic, minimalist (default)' }),
        ).toBeTruthy()
        expect(within(group).getByRole('button', { name: 'planner persona: canopy (default)' })).toBeTruthy()
        expect(within(group).getByRole('button', { name: 'worker persona: canopy (default)' })).toBeTruthy()
        const models = within(group).getAllByRole('button', { name: /model: default$/u })
        expect(models.map((b) => b.getAttribute('aria-label'))).toEqual([
            'planner model: default',
            'worker model: default',
            'reviewer model: default',
        ])
        expect(models[1]?.title).toBe('canopy model KEY M --agent worker')
        // What each default is: config's for the worker, the runtime's for the others.
        expect(await within(group).findByText('acme/fast-1')).toBeTruthy()
        expect(within(group).getAllByText('runtime default')).toHaveLength(2)
    })

    it("sends each pick with the start, as the ticket's overrides, and says how many while folded", async () => {
        const { router } = await renderRouted(<StartTicket />, { at: '/tickets' })
        showOverrides()
        let menu = await openPersonas('planner persona: canopy (default)')
        fireEvent.click(within(menu).getByRole('menuitemradio', { name: 'skeptic' }))
        expect(await screen.findByRole('button', { name: 'planner persona: skeptic' })).toBeTruthy()
        menu = await openPersonas('worker persona: canopy (default)')
        fireEvent.click(within(menu).getByRole('menuitemradio', { name: 'minimalist' }))
        // A pick dropped again is not sent.
        menu = await openPersonas('worker persona: minimalist')
        fireEvent.click(within(menu).getByRole('menuitem', { name: 'Use the default' }))
        expect(await screen.findByRole('button', { name: 'worker persona: canopy (default)' })).toBeTruthy()
        const list = await openModels('reviewer model: default')
        fireEvent.click(within(list).getByRole('option', { name: 'acme/deep-2@high' }))
        expect(await screen.findByRole('button', { name: 'reviewer model: acme/deep-2@high' })).toBeTruthy()
        // Folded, the picks are still sent, and the disclosure says they are there; folding it sent nothing.
        fireEvent.click(screen.getByRole('button', { name: 'Hide persona and model overrides' }))
        expect(screen.getByText('2 picked')).toBeTruthy()
        expect(sent).toEqual([])
        start('ABC-1')
        await waitFor(() => {
            expect(router.state.location.pathname).toBe('/tickets/ABC-1')
        })
        expect(bodies).toEqual([
            {
                personas: [{ agent: 'planner', persona: 'skeptic' }],
                models: [{ agent: 'reviewer', model: 'acme/deep-2@high' }],
                plan: null,
            },
        ])
    })

    it('sends nothing for a blank key', async () => {
        await renderRouted(<StartTicket />)
        start('   ')
        expect(sent).toEqual([])
    })

    it('names the guard that refused it, in place of the hint, and stays on the page', async () => {
        answer = Response.json({ detail: { guard: 'done', reason: 'ABC-1 is done' } }, { status: 409 })
        const { router } = await renderRouted(<StartTicket />, { at: '/tickets' })
        start('ABC-1')
        expect((await screen.findByRole('alert')).textContent).toBe('refused (done): ABC-1 is done')
        expect(screen.queryByRole('status')).toBeNull()
        expect(router.state.location.pathname).toBe('/tickets')
    })
})
