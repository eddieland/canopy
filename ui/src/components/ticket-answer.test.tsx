import { QueryClient } from '@tanstack/react-query'
import { act, cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { mockAttention, mockNoAttachments, mockTickets } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { AttentionItem, Limit, Message, TicketDetail, TicketSummary } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { TicketAnswer, TicketVerbs } from './ticket-answer'

const TICKET = mockTickets[0] as TicketSummary
const ITEM = mockAttention[0] as AttentionItem

const QUESTION: Message = {
    id: 5,
    at: '2026-10-08T11:56:00Z',
    body: 'Should the export button be red or blue?',
    source: 'worker',
    kind: 'question',
    channel: 'run',
    answers: null,
    run_id: null,
    task_run_id: null,
    comment: null,
}

// The ticket at its resume limit in web, so the grant shows too.
const AT_LIMIT: Limit = { kind: 'resume', repo: 'web', pr_url: null, runs: 2, limit: 2, granted: 0 }

const DETAIL: TicketDetail = {
    ticket: TICKET,
    units: [],
    attachments: mockNoAttachments,
    limits: [AT_LIMIT],
    runs: [],
    messages: [QUESTION],
    forgets: [],
    decisions: [],
    cost: { runs: 0, reviews: 0, priced: 0, cost_usd: null, models: [], unread_cost_usd: null },
    drafts: [],
    personas: [],
    persona_names: [],
    models: [],
    worker_models: [],
}

// Every reply sent, each recorded as a new message answering the question.
let sent: string[] = []

const server: Middleware = {
    onRequest({ request }) {
        sent.push(new URL(request.url).pathname)
        return Response.json({ message_id: 9, answers: 5, new: true })
    },
}

beforeEach(() => {
    sent = []
    sessionStorage.clear()
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
    localStorage.clear()
})

// The answer under a client that fetches nothing, holding `attention` as the attention list.
async function renderAnswer(props: Partial<Parameters<typeof TicketAnswer>[0]> = {}, attention = [ITEM]) {
    const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
    client.setQueryData(keys.attention, attention)
    const result = await renderRouted(
        <TicketAnswer
            detail={DETAIL}
            after={<TicketVerbs ticket={TICKET} limits={DETAIL.limits} place="after" testId="actions" />}
            {...props}
        />,
        { client },
    )
    return { ...result, client }
}

// Whether `a` comes before `b` in the document, which is the order Tab moves through them.
function before(a: Element, b: Element): boolean {
    return Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)
}

describe('TicketAnswer', () => {
    it('puts the reply right after the conversation, and the verbs and the grant after the reply', async () => {
        await renderAnswer()
        const conversation = screen.getByRole('region', { name: 'Conversation' })
        const reply = screen.getByRole('textbox', { name: 'Reply to message 5' })
        const stop = screen.getByRole('button', { name: 'Stop' })
        const grant = screen.getByRole('button', { name: 'Allow one more' })
        expect(before(conversation, reply)).toBe(true)
        expect(before(reply, stop)).toBe(true)
        expect(before(stop, grant)).toBe(true)
        // Nothing the keyboard stops at sits between the conversation and the reply.
        const between = [...document.querySelectorAll('a, button, textarea, input, [tabindex]')].filter(
            (el) => before(conversation, el) && !conversation.contains(el) && before(el, reply),
        )
        expect(between).toEqual([])
    })

    it("on an attention item, wears the ticket's chip and phase over the conversation", async () => {
        await renderAnswer({ item: true })
        expect(screen.getByText('private', { exact: true })).toBeTruthy()
        expect(screen.getByText('needs human')).toBeTruthy()
    })

    it('tells its caller what a reply did', async () => {
        const onReplied = vi.fn<(replied: unknown, said: string) => void>()
        await renderAnswer({ onReplied })
        fireEvent.change(screen.getByRole('textbox', { name: 'Reply to message 5' }), { target: { value: 'Blue.' } })
        fireEvent.click(screen.getByRole('button', { name: /^Reply/u }))
        await waitFor(() => expect(onReplied).toHaveBeenCalledTimes(1))
        expect(sent).toEqual(['/api/tickets/ABC-102/replies'])
        expect(onReplied.mock.calls[0]?.[1]).toBe(
            'Recorded message 9 on ABC-102, answering message 5. The next tick reads it.',
        )
    })

    it("drops a leaf when one of the ticket's items clears while it is shown, and only then", async () => {
        const other = { ...ITEM, id: 'b2', subject: 'ABC-200', ticket_key: 'ABC-200' }
        const untrusted = { ...ITEM, id: 'u1', reason: 'untrusted_review' }
        const { client } = await renderAnswer({ detail: { ...DETAIL, ticket: { ...TICKET, private: false } } }, [
            ITEM,
            other,
        ])
        // Another ticket's item clearing is not this one's, nor is an item arriving: the box asks about the review.
        act(() => {
            client.setQueryData(keys.attention, [ITEM, untrusted])
        })
        const reply = screen.getByRole('textbox', { name: 'Reply to message 5' })
        await waitFor(() => expect(reply.getAttribute('placeholder')).toMatch(/untrusted review/u))
        expect(screen.queryByTestId('leaf')).toBeNull()
        act(() => {
            client.setQueryData(keys.attention, [ITEM])
        })
        const leaf = await screen.findByTestId('leaf')
        expect(leaf.getAttribute('aria-hidden')).toBe('true')
    })

    it('counts only the ticket it shows now, when the page moves to another ticket', async () => {
        const next = { ...TICKET, key: 'ABC-300', private: false }
        const nextItem = { ...ITEM, id: 'n1', subject: 'ABC-300', ticket_key: 'ABC-300' }
        // A page that stays mounted while its ticket changes, as a route does when only its key does.
        function Moving() {
            const [ticket, setTicket] = useState<TicketSummary>({ ...TICKET, private: false })
            return (
                <>
                    <button type="button" onClick={() => setTicket(next)}>
                        Next ticket
                    </button>
                    <TicketAnswer detail={{ ...DETAIL, ticket }} />
                </>
            )
        }
        const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
        client.setQueryData(keys.attention, [ITEM, nextItem])
        await renderRouted(<Moving />, { client })
        fireEvent.click(screen.getByRole('button', { name: 'Next ticket' }))
        // The item of the ticket left behind clears: it was never this ticket's, so no leaf drops here.
        act(() => {
            client.setQueryData(keys.attention, [nextItem])
        })
        await waitFor(() => expect(screen.getByRole('textbox', { name: /^Reply/u })).toBeTruthy())
        expect(screen.queryByTestId('leaf')).toBeNull()
        act(() => {
            client.setQueryData(keys.attention, [])
        })
        expect(await screen.findByTestId('leaf')).toBeTruthy()
    })

    it('drops none where the list drops its own', async () => {
        const untrusted = { ...ITEM, id: 'u1', reason: 'untrusted_review' }
        const { client } = await renderAnswer(
            { detail: { ...DETAIL, ticket: { ...TICKET, private: false } }, leaf: false },
            [ITEM, untrusted],
        )
        const reply = screen.getByRole('textbox', { name: 'Reply to message 5' })
        expect(reply.getAttribute('placeholder')).toMatch(/untrusted review/u)
        act(() => {
            client.setQueryData(keys.attention, [ITEM])
        })
        await waitFor(() => expect(reply.getAttribute('placeholder')).not.toMatch(/untrusted review/u))
        expect(screen.queryByTestId('leaf')).toBeNull()
    })
})
