import { cleanup, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { draft } from '@/api/mocks'
import { renderRouted } from '@/test-utils'

import { TicketDrafts } from './ticket-drafts'

const ISSUE = 'https://github.com/acme/api/issues/1'

afterEach(() => {
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
})
