import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { renderRouted } from '@/test-utils'

import { StartTicket } from './start-ticket'

// Every path the form posts to, and what the server stand-in answers.
let sent: string[] = []
let answer: Response | undefined

const server: Middleware = {
    onRequest({ request }) {
        sent.push(new URL(request.url).pathname)
        return answer ?? Response.json({ already: false, running_run: null, running_private: null })
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

function start(key: string) {
    fireEvent.change(screen.getByRole('textbox', { name: 'Ticket key' }), { target: { value: key } })
    fireEvent.submit(screen.getByRole('form', { name: 'Start a ticket' }))
}

describe('StartTicket', () => {
    it('says up front that it needs no queue label and keeps the conversation in canopy', async () => {
        await renderRouted(<StartTicket />)
        expect(screen.getByRole('status').textContent).toBe(
            'No queue label needed. Its conversation stays in canopy: nothing reaches the ticket.',
        )
    })

    it('starts the ticket by its key as typed, trimmed, then opens its page', async () => {
        const { router } = await renderRouted(<StartTicket />, { at: '/tickets' })
        start('  ABC-1 ')
        await waitFor(() => {
            expect(router.state.location.pathname).toBe('/tickets/ABC-1')
        })
        expect(sent).toEqual(['/api/tickets/ABC-1/start'])
    })

    it('sends nothing for a blank key', async () => {
        await renderRouted(<StartTicket />)
        start('   ')
        expect(sent).toEqual([])
    })

    it('names the guard that refused it, in place of the hint, and stays on the page', async () => {
        answer = Response.json({ detail: { guard: 'done', reason: 'ABC-1 is done' } }, { status: 409 })
        const { router } = await renderRouted(<StartTicket />, { at: '/tickets' })
        start('ABC-1')
        expect((await screen.findByRole('alert')).textContent).toBe('refused (done): ABC-1 is done')
        expect(screen.queryByRole('status')).toBeNull()
        expect(router.state.location.pathname).toBe('/tickets')
    })
})
