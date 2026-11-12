import { QueryClient, useQuery } from '@tanstack/react-query'
import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { instructionsQuery, keys } from '@/api/queries'
import type { AgentInstructions, InstructionsList, InstructionsVersions } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { InstructionsForm } from './instructions-form'

const CONFIG = '/home/me/.config/canopy'
const WORKER = `${CONFIG}/worker-instructions.md`
const RULES = 'Commit review fixes as new commits.\n'
const REVIEWS = 'Flag a change with no test.\n'

function file(agent: AgentInstructions['agent'], over: Partial<AgentInstructions> = {}): AgentInstructions {
    return {
        agent,
        key: `paths.${agent}_instructions`,
        path: `${CONFIG}/instructions/${agent}.md`,
        source: 'default',
        text: null,
        sha256: null,
        problem: null,
        missing: true,
        versions: 0,
        ...over,
    }
}

const LIST: InstructionsList = {
    files: [
        file('worker', { path: WORKER, source: 'config', text: RULES, sha256: 'aaa', missing: false, versions: 2 }),
        file('overseer'),
        file('reviewer', { text: REVIEWS, sha256: 'rrr', missing: false }),
        file('chore', {
            path: `${CONFIG}/chores.md`,
            source: 'config',
            problem: 'missing: every run of it is refused until it exists',
        }),
    ],
    max_bytes: 40,
}

const VERSIONS: InstructionsVersions = {
    versions: [
        { id: 'b', at: '2026-10-06T09:00:00Z', kind: 'edit', sha256: 'v2', size: 30, text: 'Run the linters first.\n' },
        { id: 'a', at: '2026-10-02T09:00:00Z', kind: 'edit', sha256: 'v1', size: 20, text: 'Commit small.\n' },
    ],
    keep: 10,
}

// What the server stand-in lists, each change it was sent, and what it answers a save with.
let listed: InstructionsList = LIST
let sent: { method: string; path: string; body: unknown }[] = []
let answer: (agent: string, text: string) => Response | Promise<Response>

const server: Middleware = {
    async onRequest({ request }) {
        const path = new URL(request.url).pathname
        if (path.endsWith('/versions')) {
            return Response.json(VERSIONS)
        }
        if (request.method === 'GET') {
            return Response.json(listed)
        }
        const body = (await request.json()) as { text?: string }
        sent.push({ method: request.method, path, body })
        const agent = path.split('/')[3] ?? ''
        const was = listed.files.find((f) => f.agent === agent)
        const answered = path.endsWith('/delete')
            ? Response.json({ ...was, text: null, sha256: null, missing: true, versions: 1 })
            : await answer(agent, body.text ?? '')
        // What a change wrote is what the next read lists, as the server's file would be.
        if (answered.ok) {
            const written = (await answered.clone().json()) as AgentInstructions
            listed = { ...listed, files: listed.files.map((f) => (f.agent === agent ? written : f)) }
        }
        return answered
    },
}

beforeEach(() => {
    listed = LIST
    sent = []
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

// A promise held until the test opens it: a request answered only then.
function gate(): { held: Promise<null>; open: () => void } {
    const openers: (() => void)[] = []
    const held = new Promise<null>((resolve) => {
        openers.push(() => resolve(null))
    })
    return {
        held,
        open: () => {
            for (const opener of openers) {
                opener()
            }
        },
    }
}

// The page as its route draws it: the form over the files as the query holds them, so a change's answer reaches it.
function Page() {
    const { data } = useQuery(instructionsQuery)
    return data === undefined ? null : <InstructionsForm list={data} />
}

async function renderPage(client = new QueryClient()) {
    const rendered = await renderRouted(<Page />, { at: '/settings/instructions', client })
    await screen.findByTestId('instructions-worker')
    return rendered
}

function panel(agent: AgentInstructions['agent']): HTMLElement {
    return screen.getByTestId(`instructions-${agent}`)
}

function field(agent: AgentInstructions['agent'], label: string): HTMLTextAreaElement {
    return within(panel(agent)).getByRole<HTMLTextAreaElement>('textbox', { name: `${label} standing instructions` })
}

function button(at: HTMLElement, name: string): HTMLButtonElement {
    return within(at).getByRole<HTMLButtonElement>('button', { name: new RegExp(`^${name}$`, 'u') })
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
        expect(indexEntry('Chores missing')).toBeTruthy()
        expect(panel('worker').id).toBe('worker')
        expect(panel('worker').textContent).toContain('named by paths.worker_instructions')
    })

    it("saves an agent's edit from its panel's foot, over the version it read", async () => {
        await renderPage()
        const text = field('worker', 'Worker')
        expect(text.value).toBe(RULES)
        expect(panel('worker').textContent).toContain(
            'Save writes worker-instructions.md, keeping the file as it was among its versions.',
        )
        expect(button(panel('worker'), 'Save').disabled).toBe(true)

        fireEvent.change(text, { target: { value: 'Run the linters.' } })
        // 16 bytes, and the newline the save adds.
        expect(within(panel('worker')).getByTestId('instructions-bytes').textContent).toBe('17 of 40 bytes')
        expect(panel('worker').dataset['changed']).toBe('true')
        expect(indexEntry('Worker unsaved')).toBeTruthy()
        fireEvent.click(button(panel('worker'), 'Save'))

        await within(panel('worker')).findByText('Saved worker-instructions.md: runs started from now read it.')
        expect(sent).toEqual([
            {
                method: 'PUT',
                path: '/api/instructions/worker',
                body: { text: 'Run the linters.', path: WORKER, sha256: 'aaa' },
            },
        ])
        expect(text.value).toBe('Run the linters.\n')
        expect(panel('worker').dataset['changed']).toBeUndefined()
    })

    it('reverts an edit to the text the file holds', async () => {
        await renderPage()
        fireEvent.change(field('worker', 'Worker'), { target: { value: 'Draft' } })

        fireEvent.click(button(panel('worker'), 'Revert'))

        expect(field('worker', 'Worker').value).toBe(RULES)
        expect(indexEntry('Worker')).toBeTruthy()
    })

    it('creates the default of an agent with no file, from an editor Create opens and Cancel closes', async () => {
        await renderPage()
        const overseer = panel('overseer')
        expect(overseer.textContent).toContain('None yet, so they hear nothing.')
        expect(within(overseer).queryByRole('textbox')).toBeNull()

        fireEvent.click(button(overseer, 'Create'))
        fireEvent.click(button(overseer, 'Cancel'))
        expect(within(overseer).queryByRole('textbox')).toBeNull()

        fireEvent.click(button(overseer, 'Create'))
        expect(overseer.textContent).toContain('Save makes overseer.md, readable by you alone.')
        fireEvent.change(field('overseer', 'Overseer'), { target: { value: 'Dispatch urgent first.' } })
        fireEvent.click(button(overseer, 'Save'))

        await within(overseer).findByText('Saved overseer.md: runs started from now read it.')
        expect(sent).toEqual([
            {
                method: 'PUT',
                path: '/api/instructions/overseer',
                body: { text: 'Dispatch urgent first.', path: `${CONFIG}/instructions/overseer.md`, sha256: null },
            },
        ])
        expect(field('overseer', 'Overseer').value).toBe('Dispatch urgent first.\n')
    })

    it('deletes a default after asking once more, and never offers to delete a file a key names', async () => {
        await renderPage()
        const reviewer = panel('reviewer')
        expect(within(panel('worker')).queryByRole('button', { name: 'Delete' })).toBeNull()

        fireEvent.click(button(reviewer, 'Delete'))
        const ask = within(reviewer).getByRole('group', { name: 'Delete reviewer.md?' })
        fireEvent.click(button(ask, 'Keep it'))
        expect(sent).toEqual([])

        fireEvent.click(button(reviewer, 'Delete'))
        fireEvent.click(button(within(reviewer).getByRole('group', { name: 'Delete reviewer.md?' }), 'Delete'))

        await within(reviewer).findByText('Deleted reviewer.md: runs started from now read none.')
        expect(sent).toEqual([
            {
                method: 'POST',
                path: '/api/instructions/reviewer/delete',
                body: { path: `${CONFIG}/instructions/reviewer.md`, sha256: 'rrr' },
            },
        ])
        expect(within(reviewer).queryByRole('textbox')).toBeNull()
        expect(button(reviewer, 'Create')).toBeTruthy()
    })

    it('lists the kept versions when opened, and restores one into the editor as an edit to save', async () => {
        await renderPage()
        const worker = panel('worker')
        expect(within(panel('overseer')).queryByTestId('instructions-versions')).toBeNull()

        fireEvent.click(within(worker).getByTestId('instructions-versions'))
        const [newest, oldest, ...rest] = await within(worker).findAllByTestId('instructions-version')
        if (newest === undefined || oldest === undefined) {
            throw new Error('two versions were listed')
        }
        expect(rest).toEqual([])
        expect([newest, oldest].map((r) => r.textContent)).toEqual([
            expect.stringContaining('Before an edit'),
            expect.stringContaining('Before an edit'),
        ])
        fireEvent.click(button(newest, 'Show'))
        expect(newest.textContent).toContain('Run the linters first.')

        fireEvent.click(button(oldest, 'Restore'))
        expect(field('worker', 'Worker').value).toBe('Commit small.\n')
        expect(indexEntry('Worker unsaved')).toBeTruthy()
    })

    it('says a file a key names is missing, and makes it on a save', async () => {
        await renderPage()
        const chore = panel('chore')
        expect(within(chore).getByTestId('instructions-problem').textContent).toMatch(/^missing: /u)
        expect(field('chore', 'Chores').value).toBe('')
        expect(within(chore).queryByRole('button', { name: 'Delete' })).toBeNull()

        fireEvent.change(field('chore', 'Chores'), { target: { value: 'Name a CI job by its file.' } })
        fireEvent.click(button(chore, 'Save'))

        await within(chore).findByText('Saved chores.md: runs started from now read it.')
        expect(within(chore).queryByTestId('instructions-problem')).toBeNull()
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
        expect(button(panel('worker'), 'Save').disabled).toBe(true)

        fireEvent.change(text, { target: { value: 'Short.' } })
        fireEvent.click(button(panel('worker'), 'Save'))
        await within(panel('worker')).findByText(/refused \(stale\)/u)
        // What was written stays, to save again once the file is read again.
        expect(text.value).toBe('Short.')
    })

    it('refuses to save an edit over a file read again since it began, and says so', async () => {
        const client = new QueryClient()
        await renderPage(client)
        fireEvent.change(field('worker', 'Worker'), { target: { value: 'Mine.' } })
        expect(within(panel('worker')).queryByTestId('instructions-behind')).toBeNull()

        // Changed by hand meanwhile, and read again: the edit keeps the version it began from.
        listed = {
            ...LIST,
            files: LIST.files.map((f) => (f.agent === 'worker' ? { ...f, text: 'Theirs.\n', sha256: 'ccc' } : f)),
        }
        await client.refetchQueries({ queryKey: keys.instructions })
        await within(panel('worker')).findByTestId('instructions-behind')
        fireEvent.click(button(panel('worker'), 'Save'))

        await waitFor(() => expect(sent).toHaveLength(1))
        expect(sent.at(-1)).toEqual({
            method: 'PUT',
            path: '/api/instructions/worker',
            body: { text: 'Mine.', path: WORKER, sha256: 'aaa' },
        })
    })

    it('keeps words typed while a save was on its way', async () => {
        const save = gate()
        answer = async (agent, text) => {
            await save.held
            const was = LIST.files.find((f) => f.agent === agent)
            return Response.json({ ...was, text: `${text}\n`, sha256: 'bbb', problem: null, missing: false })
        }
        await renderPage()
        fireEvent.change(field('worker', 'Worker'), { target: { value: 'First.' } })
        fireEvent.click(button(panel('worker'), 'Save'))
        fireEvent.change(field('worker', 'Worker'), { target: { value: 'First. Second.' } })

        save.open()
        await waitFor(() => expect(button(panel('worker'), 'Save').disabled).toBe(false))
        expect(field('worker', 'Worker').value).toBe('First. Second.')
        expect(indexEntry('Worker unsaved')).toBeTruthy()
    })
})
