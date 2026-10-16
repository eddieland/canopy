import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'

import { ReplyForm } from './reply-form'
import type { ReplyTarget } from './reply-form'

const TICKET: ReplyTarget = { kind: 'ticket', key: 'ABC-1', isPublic: false }
const CHORE: ReplyTarget = { kind: 'chore', name: 'deps' }

// Every reply the form sends, and what the server stand-in answers next: a failure, then the reply recorded.
let sent: { path: string; body: { body: string; submission: string } }[] = []
let answers: Response[] = []

const server: Middleware = {
    async onRequest({ request }) {
        sent.push({ path: new URL(request.url).pathname, body: (await request.json()) as never })
        return answers.shift() ?? Response.json({ message_id: sent.length, answers: null, new: true })
    },
}

beforeEach(() => {
    sent = []
    answers = []
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

function renderForm(target: ReplyTarget, waiting: number | null = null) {
    return render(
        <QueryClientProvider client={new QueryClient()}>
            <ReplyForm target={target} waiting={waiting} />
        </QueryClientProvider>,
    )
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
        expect(screen.getByText('0/4000')).toBeDefined()

        type('Reply', '   ')
        expect(send.disabled).toBe(true)
        type('Reply', 'Use the v2 API')
        expect(send.disabled).toBe(false)
        expect(screen.getByText('14/4000')).toBeDefined()
        expect(send.getAttribute('aria-keyshortcuts')).toBe('Enter')
    })

    it('names the message it answers, and on a public ticket says the reply stays in canopy', () => {
        renderForm({ ...TICKET, isPublic: true }, 3)
        const field = screen.getByRole<HTMLTextAreaElement>('textbox', { name: 'Reply to message 3' })
        expect(field.placeholder).toMatch(/^Stays in canopy, never on the ticket\./u)
    })

    it('notes something to a chore, for its next runs', () => {
        renderForm(CHORE)
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
})
