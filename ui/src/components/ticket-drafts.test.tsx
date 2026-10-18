import { QueryClient } from '@tanstack/react-query'
import { cleanup, fireEvent, screen, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { draft } from '@/api/mocks'
import { keys } from '@/api/queries'
import { renderRouted } from '@/test-utils'

import { TicketDrafts } from './ticket-drafts'

const ISSUE = 'https://github.com/acme/api/issues/1'

// The server stand-in: every write answers with the draft, dropped.
const server: Middleware = {
    onRequest() {
        return Response.json(ticketDraft())
    },
}

afterEach(() => {
    api.eject(server)
    cleanup()
})

function ticketDraft() {
    return draft({ kind: 'ticket', stance: null, comment_id: null, thread_id: null, issue_url: ISSUE })
}

describe('TicketDrafts', () => {
    it('shows nothing for a ticket with no drafts', async () => {
        await renderRouted(<TicketDrafts ticketKey="ABC-1" drafts={[]} />)
        expect(screen.queryByTestId('ticket-drafts')).toBeNull()
    })

    it("names the issue each draft goes to, as the worker named it, and offers the draft's verbs", async () => {
        await renderRouted(<TicketDrafts ticketKey="ABC-1" drafts={[ticketDraft()]} />)
        expect(screen.getByText('Drafts for the ticket')).toBeTruthy()
        const card = within(screen.getByTestId('ticket-drafts')).getByTestId('draft')
        expect(within(card).getByTestId('draft-issue').textContent).toBe(`To ${ISSUE}, as the worker named it`)
        // The issue is shown to be checked, not followed: a worker named it.
        expect(within(card).queryByRole('link', { name: ISSUE })).toBeNull()
        expect(within(card).getByRole('button', { name: 'Send' })).toBeTruthy()
    })

    it('draws only the cards, without a panel, in an attention item', async () => {
        await renderRouted(<TicketDrafts ticketKey="ABC-1" drafts={[ticketDraft()]} bare />)
        expect(screen.queryByText('Drafts for the ticket')).toBeNull()
        expect(screen.getByTestId('draft')).toBeTruthy()
    })

    it("reads the ticket and the attention list again after a verb, as a PR's drafts do", async () => {
        api.use(server)
        const client = new QueryClient()
        const invalidated = vi.spyOn(client, 'invalidateQueries')
        await renderRouted(<TicketDrafts ticketKey="ABC-1" drafts={[ticketDraft()]} />, { client })
        fireEvent.click(screen.getByRole('button', { name: 'Drop' }))
        await screen.findByRole('status')
        const refreshed = invalidated.mock.calls.map(([filters]) => filters?.queryKey)
        expect(refreshed).toEqual(expect.arrayContaining([keys.ticket('ABC-1'), keys.attention]))
    })
})
