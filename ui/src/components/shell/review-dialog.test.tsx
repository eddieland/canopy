import { QueryClient } from '@tanstack/react-query'
import { act, cleanup, fireEvent, screen, waitFor } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import type { ConfigModels, PersonaList } from '@/api/types'
import { setReviewPersonas } from '@/lib/review-personas'
import { readReviewRequestDraft } from '@/lib/review-request-draft'
import { renderRouted } from '@/test-utils'

import { ReviewDialog } from './review-dialog'

const PR = 'https://github.com/acme/web/pull/88'
const PERSONAS: PersonaList = { reviewer: 'canopy', personas: [] }
const CONFIG: ConfigModels = {
    agents: [],
    chores: [],
    models_file: null,
    chores_file: null,
    user_file: '/home/me/.config/canopy/config.toml',
    private_file: '/home/me/.config/canopy/private.toml',
}

// Every review requested, by the PR it names, and what the server stand-in answers it.
let sent: (string | null)[] = []
let answer: Response | undefined

const server: Middleware = {
    onRequest({ request }) {
        const url = new URL(request.url)
        if (url.pathname === '/api/personas') {
            return Response.json(PERSONAS)
        }
        // And config's models, which the model menu, always in view, reads.
        if (url.pathname === '/api/config/models') {
            return Response.json(CONFIG)
        }
        sent.push(url.searchParams.get('url'))
        return (
            answer ??
            Response.json({
                already: false,
                request: {
                    channel: 'web',
                    created_at: '2026-10-08T11:00:00Z',
                    ended_at: null,
                    end_reason: null,
                    notes: null,
                    model: null,
                    personas: [],
                },
                running_review: null,
            })
        )
    },
}

beforeEach(() => {
    sent = []
    answer = undefined
    sessionStorage.clear()
    setReviewPersonas([])
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
    document.body.replaceChildren()
})

function renderDialog(at = '/attention') {
    return renderRouted(<ReviewDialog />, { at, client: new QueryClient() })
}

function press(key: string, init: KeyboardEventInit = {}, target: Element = document.body) {
    fireEvent.keyDown(target, { key, ...init })
}

// Pastes `text` on `target`, as the browser does: a paste event carrying it on its clipboard data.
function paste(text: string, target: Element = document.body) {
    const event = new Event('paste', { bubbles: true, cancelable: true })
    Object.defineProperty(event, 'clipboardData', { value: { getData: () => text } })
    act(() => {
        target.dispatchEvent(event)
    })
}

function dialog(): HTMLElement | null {
    return screen.queryByRole('dialog', { name: 'Review a PR' })
}

function urlField(): HTMLInputElement {
    return screen.getByRole('textbox', { name: 'PR URL' })
}

function notesField(): HTMLTextAreaElement {
    return screen.getByRole('textbox', { name: 'Notes for the reviewer (optional)' })
}

describe('ReviewDialog', () => {
    it('opens on R, in either case, with the focus in the empty URL field', async () => {
        await renderDialog()
        expect(dialog()).toBeNull()
        press('r')
        expect(dialog()).toBeTruthy()
        expect(screen.getByRole('form', { name: 'Review a PR' })).toBeTruthy()
        // Nothing else in the dialog says what becomes of the review, so its one quiet line does.
        expect(screen.getByRole('status').textContent).toBe(
            'For a PR the loop does not own. Nothing posts until you publish its draft.',
        )
        expect(urlField().value).toBe('')
        expect(document.activeElement).toBe(urlField())

        fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' })
        await waitFor(() => {
            expect(dialog()).toBeNull()
        })
        // Caps Lock types it upper case, with no Shift.
        press('R')
        expect(dialog()).toBeTruthy()
    })

    it('does not open on R with a modifier, or typed in a text field or the plan editor', async () => {
        await renderDialog()
        press('r', { ctrlKey: true })
        press('r', { metaKey: true })
        press('r', { altKey: true })
        press('R', { shiftKey: true })
        const input = document.createElement('input')
        const editor = document.createElement('div')
        editor.contentEditable = 'true'
        document.body.append(input, editor)
        press('r', {}, input)
        press('r', {}, editor)
        expect(dialog()).toBeNull()
    })

    it('does not open over another dialog, such as the jump palette or 2048', async () => {
        await renderDialog()
        const other = document.createElement('div')
        other.setAttribute('role', 'dialog')
        document.body.append(other)
        press('r')
        paste(PR)
        expect(dialog()).toBeNull()
    })

    it("opens on a PR's page with that PR's URL filled in, the focus in the notes", async () => {
        await renderDialog(`/pull-requests/pr?url=${encodeURIComponent(PR)}`)
        press('r')
        expect(urlField().value).toBe(PR)
        expect(document.activeElement).toBe(notesField())
    })

    it("opens on a PR's URL pasted outside a field, with it filled in, and ignores any other paste", async () => {
        await renderDialog()
        paste('https://example.com/acme/web/pull/88')
        paste(`${PR} and more`)
        paste('ABC-102')
        expect(dialog()).toBeNull()

        const input = document.createElement('input')
        document.body.append(input)
        paste(PR, input)
        expect(dialog()).toBeNull()

        // A link into one of the PR's threads names the PR.
        const thread = `${PR}#discussion_r123`
        paste(`  ${thread}\n`)
        expect(urlField().value).toBe(thread)
        expect(document.activeElement).toBe(notesField())
    })

    it('keeps what was written across closing and opening, until a request goes through', async () => {
        const { router } = await renderDialog()
        press('r')
        fireEvent.change(urlField(), { target: { value: PR } })
        fireEvent.change(notesField(), { target: { value: 'Mind the migration' } })
        fireEvent.keyDown(notesField(), { key: 'Escape' })
        await waitFor(() => {
            expect(dialog()).toBeNull()
        })

        press('r')
        expect(urlField().value).toBe(PR)
        expect(notesField().value).toBe('Mind the migration')

        fireEvent.click(screen.getByRole('button', { name: 'Review' }))
        await waitFor(() => {
            expect(router.state.location.pathname).toBe('/pull-requests/pr')
        })
        expect(router.state.location.search).toEqual({ url: PR })
        expect(sent).toEqual([PR])
        expect(dialog()).toBeNull()
        expect(readReviewRequestDraft()).toEqual({ url: '', notes: '', picked: null, model: null })
    })

    it('stays open on a refusal, naming its guard', async () => {
        answer = Response.json(
            { detail: { guard: 'loop_pr', reason: 'canopy opened this PR, and reviews it on its own' } },
            { status: 409 },
        )
        await renderDialog()
        paste(PR)
        fireEvent.click(screen.getByRole('button', { name: 'Review' }))
        expect((await screen.findByRole('alert')).textContent).toContain('loop_pr')
        expect(dialog()).toBeTruthy()
        expect(readReviewRequestDraft().url).toBe(PR)
    })
})
