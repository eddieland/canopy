import { QueryClient } from '@tanstack/react-query'
import { cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { renderRouted } from '@/test-utils'

import { TicketDialog } from './ticket-dialog'

// Every path the form posts to, and what the server stand-in answers.
let sent: string[] = []
let answer: Response | undefined

const server: Middleware = {
    onRequest({ request }) {
        // The settings the form reads for `policy.plan`: none set, so it follows `off`.
        if (request.method === 'GET') {
            return Response.json({ keys: [] })
        }
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
    document.body.replaceChildren()
})

function renderDialog(at = '/attention') {
    return renderRouted(<TicketDialog />, { at, client: new QueryClient() })
}

function press(key: string, init: KeyboardEventInit = {}, target: Element = document.body) {
    fireEvent.keyDown(target, { key, ...init })
}

function dialog(): HTMLElement | null {
    return screen.queryByRole('dialog', { name: 'Start a ticket' })
}

function keyField(): HTMLInputElement {
    return screen.getByRole('textbox', { name: 'Ticket key' })
}

function start(key: string) {
    fireEvent.change(keyField(), { target: { value: key } })
    fireEvent.submit(screen.getByRole('form', { name: 'Start a ticket' }))
}

describe('TicketDialog', () => {
    it('opens on T, in either case, with the focus in the empty key field', async () => {
        await renderDialog()
        expect(dialog()).toBeNull()
        press('t')
        expect(dialog()).toBeTruthy()
        expect(keyField().value).toBe('')
        expect(document.activeElement).toBe(keyField())

        fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' })
        await waitFor(() => {
            expect(dialog()).toBeNull()
        })
        // Caps Lock types it upper case, with no Shift.
        press('T')
        expect(dialog()).toBeTruthy()
    })

    it('does not open on T with a modifier, held, or typed in a text field or the plan editor', async () => {
        await renderDialog()
        press('t', { ctrlKey: true })
        press('t', { metaKey: true })
        press('t', { altKey: true })
        press('T', { shiftKey: true })
        press('t', { repeat: true })
        const input = document.createElement('input')
        const editor = document.createElement('div')
        editor.contentEditable = 'true'
        document.body.append(input, editor)
        press('t', {}, input)
        press('t', {}, editor)
        expect(dialog()).toBeNull()
    })

    it('does not open over another dialog, such as the jump palette or Review a PR', async () => {
        await renderDialog()
        const other = document.createElement('div')
        other.setAttribute('role', 'dialog')
        document.body.append(other)
        press('t')
        expect(dialog()).toBeNull()
    })

    it("starts the ticket, closes, and opens the ticket's page", async () => {
        const { router } = await renderDialog()
        press('t')
        start(' ABC-7 ')
        await waitFor(() => {
            expect(router.state.location.pathname).toBe('/tickets/ABC-7')
        })
        expect(sent).toEqual(['/api/tickets/ABC-7/start'])
        await waitFor(() => {
            expect(dialog()).toBeNull()
        })
    })

    it('stays open on a refusal, naming its guard', async () => {
        answer = Response.json({ detail: { guard: 'done', reason: 'ABC-1 is done' } }, { status: 409 })
        const { router } = await renderDialog()
        press('t')
        start('ABC-1')
        expect((await screen.findByRole('alert')).textContent).toBe('refused (done): ABC-1 is done')
        expect(dialog()).toBeTruthy()
        expect(router.state.location.pathname).toBe('/attention')
    })
})
