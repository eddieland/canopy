import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import type { AgentInstructions, InstructionsList } from '@/api/types'

import { InstructionsPanel } from './instructions-panel'

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

function renderPanel() {
    return render(
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
            <InstructionsPanel />
        </QueryClientProvider>,
    )
}

/** The agent's part of the panel, once the files are read. */
function section(agent: AgentInstructions['agent']): Promise<HTMLElement> {
    return screen.findByTestId(`instructions-${agent}`)
}

function field(at: HTMLElement, label: string): HTMLTextAreaElement {
    return within(at).getByRole<HTMLTextAreaElement>('textbox', { name: `${label} standing instructions` })
}

function button(at: HTMLElement, name: string): HTMLButtonElement {
    return within(at).getByRole<HTMLButtonElement>('button', { name })
}

function pick(name: string | RegExp) {
    fireEvent.click(screen.getByRole('radio', { name }))
}

describe('InstructionsPanel', () => {
    it("shows the worker's file first, in the editor, and saves an edit over the version it read", async () => {
        renderPanel()
        const worker = await section('worker')
        const text = field(worker, 'Worker')
        expect(text.value).toBe(RULES)
        expect(worker.hidden).toBe(false)
        expect(worker.textContent).toContain(WORKER)
        expect(button(worker, 'Save').disabled).toBe(true)

        fireEvent.change(text, { target: { value: 'Run the linters.' } })
        // 16 bytes, and the newline the save adds.
        expect(within(worker).getByTestId('instructions-bytes').textContent).toBe('17 of 40 bytes')
        fireEvent.click(button(worker, 'Save'))

        await within(worker).findByText(`Saved ${WORKER}.`)
        expect(saves).toEqual([{ path: '/api/instructions/worker', body: { text: 'Run the linters.', sha256: 'aaa' } }])
        expect(text.value).toBe('Run the linters.\n')
        expect(button(worker, 'Save').disabled).toBe(true)
    })

    it('keeps what was written for an agent while another is shown, marked unsaved, until Revert', async () => {
        renderPanel()
        const worker = await section('worker')
        fireEvent.change(field(worker, 'Worker'), { target: { value: 'Draft' } })
        expect(screen.getByRole('radio', { name: 'Worker unsaved' })).toBeTruthy()

        pick('Overseer')
        expect(worker.hidden).toBe(true)
        expect((await section('overseer')).hidden).toBe(false)
        pick('Worker unsaved')
        expect(field(worker, 'Worker').value).toBe('Draft')

        fireEvent.click(button(worker, 'Revert'))
        expect(field(worker, 'Worker').value).toBe(RULES)
        expect(screen.getByRole('radio', { name: 'Worker' })).toBeTruthy()
    })

    it('says an agent whose key names no file hears none, and offers no editor', async () => {
        renderPanel()
        const overseer = await section('overseer')

        expect(overseer.textContent).toContain('paths.overseer_instructions names no file, so none of them hears any.')
        expect(within(overseer).queryByRole('textbox')).toBeNull()
    })

    it('says a file the config names is missing, and makes it on a save', async () => {
        renderPanel()
        const reviewer = await section('reviewer')
        pick('Reviewer')

        expect(within(reviewer).getByTestId('instructions-problem').textContent).toMatch(/^missing: /u)
        const text = field(reviewer, 'Reviewer')
        expect(text.value).toBe('')
        fireEvent.change(text, { target: { value: 'Flag missing tests.' } })
        fireEvent.click(button(reviewer, 'Save'))

        await within(reviewer).findByText(`Saved ${REVIEWER}.`)
        expect(saves).toEqual([
            { path: '/api/instructions/reviewer', body: { text: 'Flag missing tests.', sha256: null } },
        ])
        expect(within(reviewer).queryByTestId('instructions-problem')).toBeNull()
    })

    it('holds a save past the bound a run takes, and names a refusal by its guard', async () => {
        answer = () =>
            Response.json(
                { detail: { guard: 'stale', reason: `${WORKER} changed since the page read it` } },
                { status: 409 },
            )
        renderPanel()
        const worker = await section('worker')
        const text = field(worker, 'Worker')

        fireEvent.change(text, { target: { value: 'x'.repeat(41) } })
        expect(within(worker).getByTestId('instructions-bytes').textContent).toBe(
            '42 of 40 bytes: a run would refuse it',
        )
        expect(button(worker, 'Save').disabled).toBe(true)

        fireEvent.change(text, { target: { value: 'Short.' } })
        fireEvent.click(button(worker, 'Save'))
        await within(worker).findByText(/refused \(stale\)/u)
        // What was written stays, to save again once the file is read again.
        expect(text.value).toBe('Short.')
    })
})
