import { QueryClient } from '@tanstack/react-query'
import { cleanup, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import { keys } from '@/api/queries'
import { renderRouted } from '@/test-utils'

import { Fields } from './fields'
import { TicketField } from './ticket-field'

afterEach(() => {
    cleanup()
})

function renderField(field: ReactNode) {
    const client = new QueryClient()
    client.setQueryDefaults(keys.meta, { enabled: false })
    return renderRouted(<Fields>{field}</Fields>, { client })
}

describe('TicketField', () => {
    it('opens the ticket, then says the run’s kind and the ticket’s title', async () => {
        await renderField(<TicketField ticketKey="ABC-101" title="Sign in with SSO" kind="fix_ci" />)
        expect(screen.getByRole('term').textContent).toBe('ticket')
        expect(screen.getByRole('link', { name: 'ABC-101' }).getAttribute('href')).toBe('/tickets/ABC-101')
        expect(screen.getByRole('definition').textContent).toBe('ABC-101fix ciSign in with SSO')
    })

    it('says untitled for a ticket the overseer has not named, and no kind when the page is not a run’s', async () => {
        await renderField(<TicketField ticketKey="ABC-101" title={null} />)
        expect(screen.getByRole('definition').textContent).toBe('ABC-101untitled')
    })

    it('says why a PR canopy only reviews has no ticket', async () => {
        await renderField(<TicketField ticketKey={null} title={null} />)
        expect(screen.queryByRole('link')).toBeNull()
        expect(screen.getByRole('definition').textContent).toBe('none: canopy only reviews it')
    })

    it('leaves the reason to a page that already says it', async () => {
        await renderField(<TicketField ticketKey={null} title={null} why={false} />)
        expect(screen.getByRole('definition').textContent).toBe('none')
    })
})
