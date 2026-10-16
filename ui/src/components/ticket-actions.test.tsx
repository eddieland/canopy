import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import type { TicketSummary } from '@/api/types'

import { TicketActions } from './ticket-actions'

const TICKET: TicketSummary = {
    key: 'ABC-1',
    title: 'Export reports as CSV',
    private: true,
    start: 'started',
    phase: 'implementing',
    last_decision: null,
    done: false,
    branch: 'agent/ABC-1-export',
    active_at: '2026-10-08T11:56:00Z',
    latest_message_id: null,
    awaiting: null,
    running_run: null,
}

// Every action the buttons send, and what the server stand-in answers each.
let sent: { path: string; body: unknown }[] = []
let answer: Response | undefined

const server: Middleware = {
    async onRequest({ request }) {
        const text = await request.text()
        sent.push({ path: new URL(request.url).pathname, body: text ? (JSON.parse(text) as unknown) : undefined })
        return answer ?? Response.json({})
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

function renderActions(ticket: Partial<TicketSummary> = {}) {
    return render(
        <QueryClientProvider client={new QueryClient()}>
            <TicketActions ticket={{ ...TICKET, ...ticket }} />
        </QueryClientProvider>,
    )
}

// The names of the buttons shown, in order.
function buttons(): string[] {
    return screen.getAllByRole('button').map((button) => button.textContent)
}

describe('TicketActions', () => {
    it.each([
        ['a public ticket never started here', { private: false, start: null }, ['Start privately', 'Forget']],
        ['a private ticket stopped', { start: 'stopped' }, ['Start again', 'Forget']],
        ['a private ticket started', {}, ['Stop', 'Forget']],
        ['a private ticket a run works', { running_run: 7 }, ['Stop', 'Stop now', 'Forget']],
        ['a public ticket a run works', { private: false, start: null, running_run: 7 }, ['Start privately', 'Forget']],
    ] as const)('offers %s the verbs it can take', (_, ticket, shown) => {
        renderActions(ticket)
        expect(buttons()).toEqual(shown)
    })

    it('says how to stop a public ticket a run works, since it has no Stop', () => {
        renderActions({ private: false, start: null, running_run: 7 })
        expect(screen.getByText('Public: remove its queue label to stop it, or start it privately.')).toBeDefined()
    })

    it('asks once more before Stop now ends the run, and keeps it running when told', async () => {
        answer = Response.json({ already: false, running_run: 7, ended: true, now: true })
        renderActions({ running_run: 7 })

        fireEvent.click(screen.getByRole('button', { name: 'Stop now' }))
        expect(buttons()).toEqual(['Stop', 'End run 7 now', 'Keep it running'])
        fireEvent.click(screen.getByRole('button', { name: 'Keep it running' }))
        expect(buttons()).toEqual(['Stop', 'Stop now', 'Forget'])
        expect(sent).toEqual([])

        fireEvent.click(screen.getByRole('button', { name: 'Stop now' }))
        fireEvent.click(screen.getByRole('button', { name: 'End run 7 now' }))
        expect((await screen.findByRole('status')).textContent).toBe(
            'ABC-1 is stopped; nothing dispatches it now. Run 7 was ended and its slots returned.',
        )
        expect(sent).toEqual([{ path: '/api/tickets/ABC-1/stop', body: { now: true } }])
    })

    it('forgets only once the key is typed out exactly, and keeps the ticket when told', async () => {
        answer = Response.json({ branch: 'agent/ABC-1-export', prs: [] })
        renderActions()

        fireEvent.click(screen.getByRole('button', { name: 'Forget' }))
        expect(screen.getByRole('form', { name: 'Forget' })).toBeDefined()
        const field = screen.getByRole('textbox', { name: 'Type ABC-1 to confirm' })
        const confirm = screen.getByRole<HTMLButtonElement>('button', { name: 'Forget ABC-1' })
        expect(confirm.disabled).toBe(true)
        fireEvent.change(field, { target: { value: 'abc-1' } })
        expect(confirm.disabled).toBe(true)

        fireEvent.click(screen.getByRole('button', { name: 'Keep it' }))
        expect(screen.queryByRole('form', { name: 'Forget' })).toBeNull()

        fireEvent.click(screen.getByRole('button', { name: 'Forget' }))
        fireEvent.change(screen.getByRole('textbox', { name: 'Type ABC-1 to confirm' }), { target: { value: 'ABC-1' } })
        fireEvent.click(screen.getByRole('button', { name: 'Forget ABC-1' }))
        expect((await screen.findByRole('status')).textContent).toMatch(
            /^ABC-1 is forgotten: its next implement starts over on a new branch\. canopy no longer tracks branch/u,
        )
        expect(sent).toEqual([{ path: '/api/tickets/ABC-1/forget', body: { confirm: 'ABC-1' } }])
        expect(screen.queryByRole('form', { name: 'Forget' })).toBeNull()
    })

    it('starts a ticket privately and says so, or names the guard that refused it', async () => {
        answer = Response.json({ already: false, running_run: null, running_private: null })
        const { unmount } = renderActions({ private: false, start: null })
        fireEvent.click(screen.getByRole('button', { name: 'Start privately' }))
        expect((await screen.findByRole('status')).textContent).toBe(
            'ABC-1 is started, privately: workers read it and write nothing to it. The next tick picks it up.',
        )
        expect(sent.map((request) => request.path)).toEqual(['/api/tickets/ABC-1/start'])
        unmount()

        answer = Response.json({ detail: { guard: 'done', reason: 'ABC-1 is done' } }, { status: 409 })
        renderActions({ private: false, start: null })
        fireEvent.click(screen.getByRole('button', { name: 'Start privately' }))
        expect((await screen.findByRole('alert')).textContent).toBe('refused (done): ABC-1 is done')
    })
})
