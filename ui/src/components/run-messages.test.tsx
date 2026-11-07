import { QueryClient } from '@tanstack/react-query'
import { cleanup, fireEvent, screen, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import type { RunMessage } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { RunMessagesPanel } from './run-messages'
import type { MessageTarget } from './run-messages'

const RUN: MessageTarget = { kind: 'run', id: 41 }

const FETCHED: RunMessage = {
    id: 7,
    at: '2026-10-08T11:50:00Z',
    body: 'Drop the logout half: ABC-107 has it now.',
    delivered_at: '2026-10-08T11:50:00Z',
    fetched_at: '2026-10-08T11:52:00Z',
}
const WAITING: RunMessage = {
    id: 9,
    at: '2026-10-08T11:58:00Z',
    body: 'And keep the old form behind a flag.',
    delivered_at: '2026-10-08T11:58:00Z',
    fetched_at: null,
}
const UNWRITTEN: RunMessage = { ...WAITING, id: 10, body: 'One more thing.', delivered_at: null }

// Every message the form sends, and what the server stand-in answers next.
let sent: { path: string; body: { body: string; submission: string } }[] = []
let answer: Response | null = null

const server: Middleware = {
    async onRequest({ request }) {
        sent.push({ path: new URL(request.url).pathname, body: (await request.json()) as never })
        return answer ?? Response.json({ message_id: 12, new: true, told: true })
    },
}

beforeEach(() => {
    sent = []
    answer = null
    sessionStorage.clear()
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

function renderPanel(messages: RunMessage[], running: boolean, target: MessageTarget = RUN) {
    // Nothing is read: the panel shows what the page read.
    const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
    return renderRouted(<RunMessagesPanel messages={messages} running={running} target={target} />, { client })
}

// Each message's line, in the order shown.
function shown(): string[] {
    return within(screen.getByRole('list', { name: 'Your messages to it' }))
        .getAllByRole('listitem')
        .map((item) => item.textContent)
}

describe('RunMessagesPanel', () => {
    it('opens the form on a running run sent nothing yet, its box saying how its agent hears it', async () => {
        await renderPanel([], true)
        expect(screen.getByRole('region', { name: 'Messages to it' }).textContent).toContain('none sent')
        expect(screen.queryByRole('list', { name: 'Your messages to it' })).toBeNull()
        const field = screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Message' })
        expect(field.placeholder).toMatch(/Its agent hears that it waits on its next tool call\.$/u)
        expect(screen.getByRole<HTMLButtonElement>('button', { name: 'Send' }).disabled).toBe(true)
    })

    it('lists what was sent, oldest first, and whether its agent fetched each, as canopy show does', async () => {
        await renderPanel([FETCHED, WAITING, UNWRITTEN], true)
        expect(screen.getByText('3 sent · 1 fetched')).toBeDefined()
        const [fetched, waiting, unwritten] = shown()
        expect(fetched).toMatch(/^#7sent .* agofetched .* agoDrop the logout half/u)
        expect(waiting).toContain('not fetched yet')
        expect(unwritten).toContain('not written where its agent reads it yet')
    })

    it('takes no message once the run has ended, and says which were never fetched', async () => {
        await renderPanel([FETCHED, WAITING], false)
        expect(screen.queryByRole('form')).toBeNull()
        expect(shown()[1]).toContain('never fetched')
        cleanup()

        const { container } = await renderPanel([], false)
        expect(container.textContent).toBe('')
    })

    it('sends a message to the run, saying in the CLI’s words that its agent hears it', async () => {
        await renderPanel([], true)
        fireEvent.change(screen.getByRole('textbox', { name: 'Message' }), { target: { value: 'Skip the docs' } })
        fireEvent.click(screen.getByRole('button', { name: 'Send' }))
        expect((await screen.findByRole('status')).textContent).toBe(
            'Recorded message 12 to run:41. Its agent hears that it waits on its next tool call, and reads it ' +
                "through canopy's tool.",
        )
        expect(sent.map((request) => [request.path, request.body.body])).toEqual([
            ['/api/runs/41/messages', 'Skip the docs'],
        ])
    })

    it('says a message its agent was not told of reaches the ticket’s next run', async () => {
        answer = Response.json({ message_id: 13, new: true, told: false })
        await renderPanel([], true)
        fireEvent.change(screen.getByRole('textbox', { name: 'Message' }), { target: { value: 'Skip the docs' } })
        fireEvent.click(screen.getByRole('button', { name: 'Send' }))
        expect((await screen.findByRole('status')).textContent).toMatch(
            /^Recorded message 13 to run:41\. Its agent was not told of it.*: the ticket's next run reads it\.$/u,
        )
    })

    it('names the guard that refused a message, as the CLI does', async () => {
        answer = Response.json(
            { detail: { guard: 'ended', reason: 'run:41 has ended (done); reply to its ticket instead' } },
            { status: 409 },
        )
        await renderPanel([], true)
        fireEvent.change(screen.getByRole('textbox', { name: 'Message' }), { target: { value: 'Skip the docs' } })
        fireEvent.click(screen.getByRole('button', { name: 'Send' }))
        expect((await screen.findByRole('alert')).textContent).toBe(
            'refused (ended): run:41 has ended (done); reply to its ticket instead',
        )
    })

    it('sends a task’s running run its message as a reply to the task', async () => {
        answer = Response.json({ message_id: 15, answers: null, new: true, running_run: 6, told: true })
        await renderPanel([], true, { kind: 'task', id: 4 })
        const field = screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Reply' })
        expect(field.placeholder).toMatch(/^Its running agent hears that it waits on its next tool call/u)
        fireEvent.change(field, { target: { value: 'Rename it in api too' } })
        fireEvent.click(screen.getByRole('button', { name: 'Reply' }))
        await screen.findByRole('status')
        expect(sent.map((request) => request.path)).toEqual(['/api/tasks/4/replies'])
    })
})
