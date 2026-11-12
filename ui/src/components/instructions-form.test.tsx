import { useQuery } from '@tanstack/react-query'
import { cleanup, fireEvent, screen, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { instructionsQuery } from '@/api/queries'
import type { AgentInstructions, InstructionsList } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { InstructionsForm } from './instructions-form'

const WORKER = '/home/me/.config/canopy/worker.md'
const REVIEWER = '/home/me/.config/canopy/reviewer.md'
const RULES = 'Commit review fixes as new commits.\n'

function file(agent: AgentInstructions['agent'], over: Partial<AgentInstructions> = {}): AgentInstructions {
    return {
        agent,
        key: `paths.${agent}_instructions`,
        path: null,
        text: null,
        sha256: null,
        problem: null,
        missing: false,
        ...over,
    }
}

const LIST: InstructionsList = {
    files: [
        file('worker', { path: WORKER, text: RULES, sha256: 'aaa' }),
        file('overseer'),
        file('reviewer', {
            path: REVIEWER,
            problem: 'missing: every run of it is refused until it exists',
            missing: true,
        }),
        file('chore'),
    ],
    max_bytes: 40,
}

// Each save the server stand-in was sent, and what it answers one with.
let saves: { path: string; body: unknown }[] = []
let answer: (agent: string, text: string) => Response

const server: Middleware = {
    async onRequest({ request }) {
        const path = new URL(request.url).pathname
        if (request.method === 'PUT') {
            const body = (await request.json()) as { text: string; sha256: string | null }
            saves.push({ path, body })
            return answer(path.split('/').at(-1) ?? '', body.text)
        }
        return Response.json(LIST)
    },
}

beforeEach(() => {
    saves = []
    answer = (agent, text) => {
        const was = LIST.files.find((f) => f.agent === agent)
        return Response.json({ ...was, text: `${text}\n`, sha256: 'bbb', problem: null, missing: false })
    }
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

// The page as its route draws it: the form over the files as the query holds them, so a save's answer reaches it.
function Page() {
    const { data } = useQuery(instructionsQuery)
    return data === undefined ? null : <InstructionsForm list={data} />
}

async function renderPage() {
    const rendered = await renderRouted(<Page />, { at: '/settings/instructions' })
    await screen.findByTestId('instructions-worker')
    return rendered
}

function panel(agent: AgentInstructions['agent']): HTMLElement {
    return screen.getByTestId(`instructions-${agent}`)
}

function field(agent: AgentInstructions['agent'], label: string): HTMLTextAreaElement {
    return within(panel(agent)).getByRole<HTMLTextAreaElement>('textbox', { name: `${label} standing instructions` })
}

function button(agent: AgentInstructions['agent'], name: string): HTMLButtonElement {
    return within(panel(agent)).getByRole<HTMLButtonElement>('button', { name })
}

function indexEntry(name: string): HTMLElement {
    return within(screen.getByRole('navigation', { name: 'Agents' })).getByRole('link', { name })
}

describe('InstructionsForm', () => {
    it('shows every agent at once, each an anchor in the index with what stops its runs', async () => {
        await renderPage()

        expect(screen.getAllByRole('region').map((r) => r.getAttribute('aria-label'))).toEqual([
            'Worker instructions',
            'Overseer instructions',
            'Reviewer instructions',
            'Chores instructions',
        ])
        expect(indexEntry('Worker').getAttribute('href')).toBe('/settings/instructions#worker')
        expect(indexEntry('Overseer none').getAttribute('href')).toBe('/settings/instructions#overseer')
        expect(indexEntry('Reviewer missing')).toBeTruthy()
        expect(panel('worker').id).toBe('worker')
    })

    it("saves an agent's edit from its panel's foot, over the version it read", async () => {
        await renderPage()
        const text = field('worker', 'Worker')
        expect(text.value).toBe(RULES)
        expect(panel('worker').textContent).toContain(WORKER)
        expect(panel('worker').textContent).toContain(
            'Save writes worker.md, keeping the file as it was as worker.md.bak.',
        )
        expect(button('worker', 'Save').disabled).toBe(true)

        fireEvent.change(text, { target: { value: 'Run the linters.' } })
        // 16 bytes, and the newline the save adds.
        expect(within(panel('worker')).getByTestId('instructions-bytes').textContent).toBe('17 of 40 bytes')
        expect(panel('worker').dataset['changed']).toBe('true')
        expect(indexEntry('Worker unsaved')).toBeTruthy()
        fireEvent.click(button('worker', 'Save'))

        await within(panel('worker')).findByText('Saved worker.md: runs started from now read it.')
        expect(saves).toEqual([{ path: '/api/instructions/worker', body: { text: 'Run the linters.', sha256: 'aaa' } }])
        expect(text.value).toBe('Run the linters.\n')
        expect(panel('worker').dataset['changed']).toBeUndefined()
        expect(button('worker', 'Save').disabled).toBe(true)
    })

    it('reverts an edit to the text the file holds', async () => {
        await renderPage()
        fireEvent.change(field('worker', 'Worker'), { target: { value: 'Draft' } })

        fireEvent.click(button('worker', 'Revert'))

        expect(field('worker', 'Worker').value).toBe(RULES)
        expect(indexEntry('Worker')).toBeTruthy()
    })

    it('says an agent whose key names no file hears none, with no editor and no actions', async () => {
        await renderPage()

        expect(panel('overseer').textContent).toContain(
            'paths.overseer_instructions names no file, so none of them hears any.',
        )
        expect(within(panel('overseer')).queryByRole('textbox')).toBeNull()
        expect(within(panel('overseer')).queryByRole('button', { name: 'Save' })).toBeNull()
    })

    it('says a file the config names is missing, and makes it on a save', async () => {
        await renderPage()
        expect(within(panel('reviewer')).getByTestId('instructions-problem').textContent).toMatch(/^missing: /u)
        expect(panel('reviewer').textContent).toContain('Save makes reviewer.md, readable by you alone.')
        const text = field('reviewer', 'Reviewer')
        expect(text.value).toBe('')

        fireEvent.change(text, { target: { value: 'Flag missing tests.' } })
        fireEvent.click(button('reviewer', 'Save'))

        await within(panel('reviewer')).findByText('Saved reviewer.md: runs started from now read it.')
        expect(saves).toEqual([
            { path: '/api/instructions/reviewer', body: { text: 'Flag missing tests.', sha256: null } },
        ])
        expect(within(panel('reviewer')).queryByTestId('instructions-problem')).toBeNull()
    })

    it('holds a save past the bound a run takes, and names a refusal by its guard', async () => {
        answer = () =>
            Response.json(
                { detail: { guard: 'stale', reason: `${WORKER} changed since the page read it` } },
                { status: 409 },
            )
        await renderPage()
        const text = field('worker', 'Worker')

        fireEvent.change(text, { target: { value: 'x'.repeat(41) } })
        expect(within(panel('worker')).getByTestId('instructions-bytes').textContent).toBe(
            '42 of 40 bytes: a run would refuse it',
        )
        expect(button('worker', 'Save').disabled).toBe(true)

        fireEvent.change(text, { target: { value: 'Short.' } })
        fireEvent.click(button('worker', 'Save'))
        await within(panel('worker')).findByText(/refused \(stale\)/u)
        // What was written stays, to save again once the file is read again.
        expect(text.value).toBe('Short.')
    })
})
