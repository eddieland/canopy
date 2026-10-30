import { QueryClient } from '@tanstack/react-query'
import { cleanup, fireEvent, screen, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import type { ConfigModels as Models, ModelList, ModelOverride } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { ConfigModels } from './config-models'

const USER = '/home/me/.config/canopy/config.toml'
const PRIVATE = '/work/.canopy/config.toml'

const MODELS: Models = {
    agents: [
        { agent: 'worker', model: 'acme/deep-2', variant: null, source: 'config' },
        { agent: 'planner', model: null, variant: null, source: 'default' },
        { agent: 'reviewer', model: 'other/review-3', variant: 'high', source: 'config' },
        { agent: 'overseer', model: null, variant: null, source: 'default' },
        { agent: 'chore', model: 'acme/fast-1', variant: null, source: 'config' },
    ],
    chores: [
        { chore: 'deps', model: 'acme/deep-2', variant: 'low', source: 'chore', agent: null },
        { chore: 'lint', model: 'acme/fast-1', variant: null, source: 'config', agent: null },
        { chore: 'sentry', model: null, variant: null, source: 'agent', agent: 'triage' },
    ],
    models_file: USER,
    chores_file: USER,
    user_file: USER,
    private_file: PRIVATE,
}

const OVERRIDES: ModelOverride[] = [
    { ticket: 'PROJ-7', agent: 'worker', model: 'acme/deep-2', variant: 'high', set_at: '2026-10-08T10:00:00Z' },
    { ticket: 'PROJ-7', agent: 'reviewer', model: 'other/review-3', variant: null, set_at: '2026-10-08T10:00:00Z' },
]

// Every path the panel reads, and what the server stand-in answers each.
let sent: string[] = []
let models: Models = MODELS
let overrides: ModelOverride[] | Response = []
let listed: ModelList | Response = { models: ['acme/deep-2', 'acme/fast-1'], variants: {}, error: null }

const server: Middleware = {
    onRequest({ request }) {
        const path = new URL(request.url).pathname
        sent.push(path)
        if (path === '/api/config/models') {
            return Response.json(models)
        }
        if (path === '/api/models/overrides') {
            return overrides instanceof Response ? overrides : Response.json(overrides)
        }
        if (path === '/api/meta') {
            return Response.json({})
        }
        return listed instanceof Response ? listed : Response.json(listed)
    },
}

beforeEach(() => {
    sent = []
    models = MODELS
    overrides = []
    listed = { models: ['acme/deep-2', 'acme/fast-1'], variants: {}, error: null }
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

function renderPanel() {
    return renderRouted(<ConfigModels />, {
        client: new QueryClient({ defaultOptions: { queries: { retry: false } } }),
    })
}

/** Each row's label and what it says, as a reader meets them. */
async function rows() {
    const values = await screen.findAllByTestId('config-model')
    return values.map((value) => [value.previousElementSibling?.textContent, value.textContent])
}

describe('ConfigModels', () => {
    it("names each agent's and each chore's model and variant, or the runtime's default, reading no list", async () => {
        await renderPanel()
        expect(await rows()).toEqual([
            ['worker', 'acme/deep-2'],
            ['planner', 'runtime default'],
            ['reviewer', 'other/review-3@high'],
            ['overseer', 'runtime default'],
            ['chore', 'acme/fast-1every chore without a model of its own'],
            ['chore:deps', 'acme/deep-2@lowown model'],
            ['chore:lint', 'acme/fast-1'],
            // config never gives an agent of the operator's own a model: its definition does.
            ['chore:sentry', 'triage, which chooses its own model in its definition'],
        ])
        // Read only: the panel has nothing to change a model with.
        expect(screen.queryByRole('combobox')).toBeNull()
        expect(screen.queryByRole('textbox')).toBeNull()
        expect(sent).not.toContain('/api/models')
    })

    it('lists no ticket with an override as none', async () => {
        await renderPanel()
        const section = await screen.findByRole('region', { name: 'Tickets with an override' })
        expect((await within(section).findByText('none')).textContent).toBe('none')
        expect(within(section).queryByRole('list')).toBeNull()
    })

    it('lists each ticket with an override, its agent, and its model, linking to the ticket', async () => {
        overrides = OVERRIDES
        await renderPanel()
        const list = await screen.findByRole('list', { name: 'Tickets with an override' })
        expect(
            within(list)
                .getAllByRole('listitem')
                .map((item) => item.textContent),
        ).toEqual(['PROJ-7workeracme/deep-2@high', 'PROJ-7reviewerother/review-3'])
        const links = within(list).getAllByRole('link', { name: 'PROJ-7' })
        expect(links.map((link) => link.getAttribute('href'))).toEqual(['/tickets/PROJ-7', '/tickets/PROJ-7'])
        expect(sent).not.toContain('/api/models')
    })

    it('says why the overrides could not be read', async () => {
        overrides = Response.json({}, { status: 500 })
        await renderPanel()
        const section = await screen.findByRole('region', { name: 'Tickets with an override' })
        expect((await within(section).findByRole('alert')).textContent).toContain('the server answered 500')
    })

    it('names the file to edit, the one both come from', async () => {
        await renderPanel()
        const where = await screen.findByTestId('config-models-where')
        expect(where.textContent).toBe(
            `Read only. Edit [runtime.models] in ${USER}, and a chore's model in its table there. ` +
                'Reload, below, reads them again.',
        )
    })

    it('names both files when the chores are in another, and where to add a model while nothing sets one', async () => {
        models = { ...MODELS, models_file: null, chores_file: PRIVATE }
        await renderPanel()
        const where = await screen.findByTestId('config-models-where')
        expect(where.textContent).toBe(
            `Read only. Nothing sets [runtime.models] yet. Add it to ${USER} for every workspace, or to ` +
                `${PRIVATE} for this one alone. A chore's model is in its [chores.NAME] table, in ${PRIVATE}. ` +
                'Reload, below, reads them again.',
        )
    })

    it("reads the runtime's list only when it is opened, as canopy models prints it", async () => {
        await renderPanel()
        await rows()
        fireEvent.click(screen.getByRole('button', { name: "Show the runtime's models" }))
        const list = await screen.findByRole('list', { name: "The runtime's models" })
        expect(
            within(list)
                .getAllByRole('listitem')
                .map((item) => item.textContent),
        ).toEqual(['acme/deep-2', 'acme/fast-1'])
        expect(sent.filter((path) => path.endsWith('/models'))).toEqual(['/api/config/models', '/api/models'])
    })

    it("names each listed model's variants after it, as a choice names one", async () => {
        listed = { models: ['acme/deep-2', 'acme/fast-1'], variants: { 'acme/deep-2': ['low', 'high'] }, error: null }
        await renderPanel()
        await rows()
        fireEvent.click(screen.getByRole('button', { name: "Show the runtime's models" }))
        const list = await screen.findByRole('list', { name: "The runtime's models" })
        expect(
            within(list)
                .getAllByRole('listitem')
                .map((item) => item.textContent),
        ).toEqual(['acme/deep-2 @low @high', 'acme/fast-1'])
    })

    it('says why the list could not be read', async () => {
        listed = { models: [], variants: {}, error: '`opencode models` exited 1' }
        await renderPanel()
        await rows()
        fireEvent.click(screen.getByRole('button', { name: "Show the runtime's models" }))
        expect((await screen.findByRole('alert')).textContent).toBe('opencode models exited 1')
    })

    it("says a read of the list that failed in a read's words, not a write's", async () => {
        listed = Response.json({}, { status: 500 })
        await renderPanel()
        await rows()
        fireEvent.click(screen.getByRole('button', { name: "Show the runtime's models" }))
        expect((await screen.findByRole('alert')).textContent).toBe('could not read it: the server answered 500')
    })
})
