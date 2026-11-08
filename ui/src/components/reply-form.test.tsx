import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { mockRuns } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { Run } from '@/api/types'

import { ReplyForm } from './reply-form'
import type { ReplyTarget } from './reply-form'

const TICKET: ReplyTarget = { kind: 'ticket', key: 'ABC-1', isPublic: false }
const CHORE: ReplyTarget = { kind: 'chore', name: 'deps', noted: true }
const TASK: ReplyTarget = { kind: 'task', id: 4 }

// Every reply the form sends, and what the server stand-in answers next: a failure, then the reply recorded. An error
// is what fetch throws when no server answers.
let sent: { path: string; body: { body: string; submission: string } }[] = []
let answers: (Response | Error)[] = []

const server: Middleware = {
    async onRequest({ request }) {
        sent.push({ path: new URL(request.url).pathname, body: (await request.json()) as never })
        const answer = answers.shift() ?? Response.json({ message_id: sent.length, answers: null, new: true })
        if (answer instanceof Error) {
            throw answer
        }
        return answer
    },
}

beforeEach(() => {
    sent = []
    answers = []
    sessionStorage.clear()
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

// Run 41 working ABC-1 now, as the stream lists it.
const RUNNING = { ...mockRuns[0], id: 41, state: 'running', ticket_key: 'ABC-1' } as Run

function renderForm(target: ReplyTarget, waiting: number | null = null, untrusted = false, runs: Run[] = []) {
    const client = new QueryClient()
    // The runs come from the stream, never a read of the form's own.
    client.setQueryDefaults(keys.runs, { enabled: false })
    client.setQueryData(keys.runs, runs)
    const rendered = render(
        <QueryClientProvider client={client}>
            <ReplyForm target={target} waiting={waiting} untrusted={untrusted} />
        </QueryClientProvider>,
    )
    return { ...rendered, client }
}

function type(label: string, text: string) {
    fireEvent.change(screen.getByRole('textbox', { name: label }), { target: { value: text } })
}

describe('ReplyForm', () => {
    it('answers a ticket, and sends only once something is written', () => {
        renderForm(TICKET)
        expect(screen.getByRole('form', { name: 'Reply' })).toBeDefined()
        const send = screen.getByRole<HTMLButtonElement>('button', { name: 'Reply' })
        expect(send.disabled).toBe(true)
        // The count stays out of the way until the reply nears its bound.
        expect(screen.queryByText(/\/4000$/u)).toBeNull()

        type('Reply', '   ')
        expect(send.disabled).toBe(true)
        type('Reply', 'Use the v2 API')
        expect(send.disabled).toBe(false)
        expect(screen.queryByText('14/4000')).toBeNull()
        expect(send.getAttribute('aria-keyshortcuts')).toBe('Enter')
        type('Reply', 'x'.repeat(3200))
        expect(screen.getByText('3200/4000')).toBeDefined()
    })

    it('names the message it answers, and on a public ticket says the reply stays in canopy', () => {
        renderForm({ ...TICKET, isPublic: true }, 3)
        const field = screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Reply to message 3' })
        expect(field.placeholder).toMatch(/It stays in canopy, never on the ticket\.$/u)
    })

    it('asks about an untrusted review only while one waits on the go-ahead', () => {
        renderForm({ ...TICKET, isPublic: true }, null, true)
        const field = screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Reply' })
        expect(field.placeholder).toMatch(/^Say what to do about the untrusted review\./u)
    })

    it('stays open on a public ticket with nothing waiting, its box saying what a note is for', () => {
        renderForm({ ...TICKET, isPublic: true })
        expect(screen.getByRole('form', { name: 'Reply' })).toBeDefined()
        expect(screen.queryByRole('button', { name: /a note for its next worker/u })).toBeNull()
        const field = screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Reply' })
        expect(field.placeholder).toMatch(/It stays in canopy, never on the ticket\.$/u)
        expect(field.placeholder).not.toMatch(/untrusted/u)
    })

    it('keeps a public ticket’s draft', () => {
        renderForm({ ...TICKET, isPublic: true })
        type('Reply', 'Leave the docs alone')
        cleanup()
        renderForm({ ...TICKET, isPublic: true })
        expect(screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Reply' }).value).toBe('Leave the docs alone')
    })

    it('notes something to a chore, for its next runs, its form open', () => {
        renderForm(CHORE)
        expect(screen.queryByRole('button', { name: /a note for its next runs/u })).toBeNull()
        expect(screen.getByRole('form', { name: 'Note' })).toBeDefined()
        expect(screen.getByRole('textbox', { name: 'Note' })).toBeDefined()
        expect(screen.getByRole('button', { name: 'Add note' })).toBeDefined()
    })

    it('says what a reply did in the CLI’s words, and clears the field for the next', async () => {
        renderForm(CHORE)
        type('Note', 'Leave lodash at 4')
        fireEvent.click(screen.getByRole('button', { name: 'Add note' }))

        const said = await screen.findByRole('status')
        expect(said.textContent).toBe('Recorded message 1 on chore:deps. Its next run reads it.')
        expect(sent.map((request) => [request.path, request.body.body])).toEqual([
            ['/api/chores/deps/replies', 'Leave lodash at 4'],
        ])
        expect(screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Note' }).value).toBe('')
    })

    it('gives a task its next instruction, saying in the CLI’s words what starts its next run', async () => {
        answers = [
            Response.json({ message_id: 14, answers: 13, new: true, running_run: null }),
            Response.json({ message_id: 15, answers: null, new: true, running_run: 6 }),
        ]
        renderForm(TASK, 13)
        const field = screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Reply to message 13' })
        expect(field.placeholder).toMatch(/^Its next run reads it as your next instruction/u)
        type('Reply to message 13', 'Yes, rename it in api too')
        fireEvent.click(screen.getByRole('button', { name: 'Reply' }))
        expect((await screen.findByRole('status')).textContent).toBe(
            'Recorded message 14 on task:4, answering message 13. The next tick starts its next run, on its branch.',
        )

        type('Reply to message 13', 'And the docs')
        fireEvent.click(screen.getByRole('button', { name: 'Reply' }))
        await screen.findByText(
            'Recorded message 15 on task:4. Its run 6 is still working; the first tick after it ends starts the ' +
                'next run.',
        )
        expect(new Set(sent.map((request) => request.path))).toEqual(new Set(['/api/tasks/4/replies']))
        // A task's draft is its own: the ticket's box starts empty.
        cleanup()
        renderForm(TASK)
        type('Reply', 'Half written')
        cleanup()
        renderForm(TICKET)
        expect(screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Reply' }).value).toBe('')
        cleanup()
        renderForm(TASK)
        expect(screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Reply' }).value).toBe('Half written')
    })

    it('sends a retry after a failure as the same submission, and the reply after it as another', async () => {
        answers = [Response.json({ detail: 'the journal is busy' }, { status: 503 })]
        renderForm(TICKET)
        type('Reply', 'Use the v2 API')
        fireEvent.click(screen.getByRole('button', { name: 'Reply' }))
        expect((await screen.findByRole('alert')).textContent).toBe('the journal is busy')

        fireEvent.click(screen.getByRole('button', { name: 'Reply' }))
        expect((await screen.findByRole('status')).textContent).toBe(
            'Recorded message 2 on ABC-1. The next tick reads it.',
        )

        type('Reply', 'And add a test')
        fireEvent.click(screen.getByRole('button', { name: 'Reply' }))
        await screen.findByText('Recorded message 3 on ABC-1. The next tick reads it.')

        const [failed, retried, next] = sent.map((request) => request.body.submission)
        expect(retried).toBe(failed)
        expect(next).not.toBe(retried)
        expect(new Set(sent.map((request) => request.path))).toEqual(new Set(['/api/tickets/ABC-1/replies']))
    })

    it('keeps an unsent reply across a sign-out, as the same submission, and forgets it once recorded', async () => {
        answers = [Response.json({ detail: 'sign in with the listener secret' }, { status: 401 })]
        const first = renderForm(TICKET)
        type('Reply', 'Use the v2 API')
        fireEvent.click(screen.getByRole('button', { name: 'Reply' }))
        await screen.findByRole('alert')
        // Signed out, the shell swaps the page for the sign-in page; signed in again, the form is drawn anew.
        first.unmount()

        renderForm(TICKET)
        expect(screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Reply' }).value).toBe('Use the v2 API')
        // The chore keeps no draft of the ticket's, so its box starts empty.
        renderForm(CHORE)
        expect(screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Note' }).value).toBe('')
        cleanup()

        renderForm(TICKET)
        fireEvent.click(screen.getByRole('button', { name: 'Reply' }))
        await screen.findByRole('status')
        const [failed, resent] = sent.map((request) => request.body.submission)
        expect(resent).toBe(failed)
        cleanup()

        renderForm(TICKET)
        expect(screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Reply' }).value).toBe('')
    })

    it('offers to tell the ticket’s running run now, off by default, and only while nothing waits on an answer', () => {
        renderForm(TICKET, null, false, [RUNNING])
        const box = screen.getByRole('checkbox', { name: 'Tell run:41 now' })
        expect(box.getAttribute('aria-checked')).toBe('false')
        const field = screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Reply' })
        expect(field.placeholder).toBe('The next worker reads it as an instruction.')
        fireEvent.click(box)
        expect(field.placeholder).toBe(
            "Run 41 hears on its next tool call that you wrote, and reads it through canopy's tool.",
        )
        cleanup()

        // Not while the form answers a question, nor with no run working the ticket, nor on a run of another ticket.
        renderForm(TICKET, 3, false, [RUNNING])
        expect(screen.queryByRole('checkbox')).toBeNull()
        cleanup()
        renderForm(TICKET, null, false, [{ ...RUNNING, ticket_key: 'ABC-2' }])
        expect(screen.queryByRole('checkbox')).toBeNull()
        cleanup()
        renderForm(TASK, null, false, [RUNNING])
        expect(screen.queryByRole('checkbox')).toBeNull()
    })

    it('sends to the run when told to, then to the ticket again, the box cleared after each send', async () => {
        answers = [Response.json({ message_id: 9, new: true, told: true })]
        renderForm(TICKET, null, false, [RUNNING])
        type('Reply', 'Drop the logout half')
        fireEvent.click(screen.getByRole('checkbox', { name: 'Tell run:41 now' }))
        fireEvent.click(screen.getByRole('button', { name: 'Reply' }))
        expect((await screen.findByRole('status')).textContent).toBe(
            'Recorded message 9 to run:41. Its agent hears that it waits on its next tool call, and reads it through ' +
                "canopy's tool.",
        )
        expect(screen.getByRole('checkbox', { name: 'Tell run:41 now' }).getAttribute('aria-checked')).toBe('false')

        type('Reply', 'And keep the old form')
        fireEvent.click(screen.getByRole('button', { name: 'Reply' }))
        await screen.findByText('Recorded message 2 on ABC-1. The next tick reads it.')
        expect(sent.map((request) => [request.path, request.body.body])).toEqual([
            ['/api/runs/41/messages', 'Drop the logout half'],
            ['/api/tickets/ABC-1/replies', 'And keep the old form'],
        ])
    })

    it('keeps the draft when the run ended first, and sends it to the ticket as the same submission', async () => {
        answers = [
            Response.json(
                // Its reason names no run, which `Notice` would link, and this test has no router.
                {
                    detail: {
                        guard: 'ended',
                        reason: 'the run has ended (done); its agent can no longer hear a message',
                    },
                },
                { status: 409 },
            ),
        ]
        const { client } = renderForm(TICKET, null, false, [RUNNING])
        type('Reply', 'Drop the logout half')
        fireEvent.click(screen.getByRole('checkbox', { name: 'Tell run:41 now' }))
        fireEvent.click(screen.getByRole('button', { name: 'Reply' }))
        expect((await screen.findByRole('alert')).textContent).toBe(
            'refused (ended): the run has ended (done); its agent can no longer hear a message',
        )
        expect(screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Reply' }).value).toBe('Drop the logout half')

        // The stream says the run ended: the box goes, and the same reply goes to the ticket.
        client.setQueryData(keys.runs, [{ ...RUNNING, status: 'done', state: 'done' }])
        await waitFor(() => {
            expect(screen.queryByRole('checkbox')).toBeNull()
        })
        fireEvent.click(screen.getByRole('button', { name: 'Reply' }))
        await screen.findByText('Recorded message 2 on ABC-1. The next tick reads it.')
        const [tried, replied] = sent
        expect([tried?.path, replied?.path]).toEqual(['/api/runs/41/messages', '/api/tickets/ABC-1/replies'])
        expect(replied?.body.submission).toBe(tried?.body.submission)
    })

    it('says a reply that reached no server in canopy’s words, not the browser’s', async () => {
        answers = [new TypeError('Failed to fetch')]
        renderForm(TICKET)
        type('Reply', 'Use the v2 API')
        fireEvent.click(screen.getByRole('button', { name: 'Reply' }))
        expect((await screen.findByRole('alert')).textContent).toBe('canopy did not answer: is canopy loop running?')
    })
})
