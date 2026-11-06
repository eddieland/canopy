import { QueryClient } from '@tanstack/react-query'
import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { keys } from '@/api/queries'
import type { Meta } from '@/api/types'
import { DictationContext } from '@/hooks/use-dictation'
import { ToastContext } from '@/hooks/use-toast'
import type { NewToast } from '@/lib/toasts'
import { renderRouted } from '@/test-utils'

import { EpicSubmitForm } from './epic-submit'

// What each submission sent, and what the server stand-in answers.
let sent: unknown[] = []
let answer: Response | undefined
let toasts: NewToast[] = []

const server: Middleware = {
    async onRequest({ request }) {
        if (request.method === 'POST' && new URL(request.url).pathname === '/api/epics') {
            sent.push(await request.json())
        }
        return answer ?? Response.json({ id: 4, repos: ['api', 'web'] })
    },
}

const GOAL = 'Let customers export their invoices as CSV.'

beforeEach(() => {
    sent = []
    answer = undefined
    toasts = []
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

/** The form at `/epics`, in a workspace of `repos`, where the server offers dictation when `dictation` says so. */
function renderForm(repos: string[], dictation = false) {
    const client = new QueryClient()
    const meta: Meta = {
        branch_urls: {},
        dictation,
        build: null,
        mock: false,
        ticket_url: null,
        version: '0.4.0',
        workspace_root: '/w',
        repos,
    }
    client.setQueryData(keys.meta, meta)
    return renderRouted(
        <DictationContext value={dictation}>
            <ToastContext
                value={(toast) => {
                    toasts.push(toast)
                }}
            >
                <EpicSubmitForm />
            </ToastContext>
        </DictationContext>,
        { at: '/epics', client },
    )
}

function write(text: string, project = '', trackerEpic = '') {
    fireEvent.change(screen.getByRole('textbox', { name: 'Goal' }), { target: { value: text } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Tracker project' }), { target: { value: project } })
    fireEvent.change(screen.getByRole('textbox', { name: 'Tracker epic' }), { target: { value: trackerEpic } })
}

// Opens the repositories' list and picks each of `repos`: it stays open, so several are picked in one go.
function pick(...repos: string[]) {
    fireEvent.click(screen.getByRole('button', { name: /^Its plan reads/u }))
    for (const repo of repos) {
        fireEvent.click(within(screen.getByRole('listbox')).getByRole('option', { name: repo }))
    }
}

function submit() {
    fireEvent.submit(screen.getByRole('form', { name: 'Submit an epic' }))
}

function submitButton() {
    return screen.getByRole<HTMLButtonElement>('button', { name: /^Submit/u })
}

describe('EpicSubmitForm', () => {
    it('says up front that no project files no tickets and a tracker epic only suggests them', async () => {
        await renderForm(['api', 'web'])
        expect(screen.getByRole('status').textContent).toBe(
            'Its plan reads only the repositories you name. With no project it files no tickets. A tracker ' +
                "epic's tickets are only suggestions: none is a member until you add it.",
        )
    })

    it('submits the goal in a workspace of one, naming no repository, then says so and opens the epic', async () => {
        const { router } = await renderForm(['web'])
        expect(screen.queryByRole('button', { name: /^Its plan reads/u })).toBeNull()
        write(GOAL)
        submit()
        await waitFor(() => {
            expect(router.state.location.pathname).toBe('/epics/4')
        })
        expect(sent).toEqual([{ text: GOAL, repos: [], project: null, tracker_epic: null }])
        expect(toasts).toEqual([
            { title: 'Submitted epic:4; the next tick starts its plan run.', detail: 'over api, web', tone: 'done' },
        ])
    })

    it('waits for its repositories to be named in a workspace of several, then sends those and the keys', async () => {
        const { router } = await renderForm(['api', 'mobile', 'web'])
        write(GOAL, '  ABC ', 'ABC-90')
        // None chosen until the operator names them, as the CLI asks: nothing is sent.
        expect(screen.getByRole('button', { name: 'Its plan reads: repositories it reads' })).toBeTruthy()
        expect(submitButton().disabled).toBe(true)
        submit()
        expect(sent).toEqual([])

        pick('web', 'api')
        expect(screen.getByRole('button', { name: 'Its plan reads: api, web' })).toBeTruthy()
        expect(submitButton().disabled).toBe(false)
        submit()
        await waitFor(() => {
            expect(router.state.location.pathname).toBe('/epics/4')
        })
        expect(sent).toEqual([{ text: GOAL, repos: ['api', 'web'], project: 'ABC', tracker_epic: 'ABC-90' }])
    })

    it('sends nothing for a blank goal', async () => {
        await renderForm(['web'])
        write('   ')
        submit()
        expect(sent).toEqual([])
        expect(submitButton().disabled).toBe(true)
    })

    it('offers dictation where the server does', async () => {
        await renderForm(['web'])
        expect(screen.queryByRole('button', { name: 'Dictate' })).toBeNull()
        cleanup()
        await renderForm(['web'], true)
        expect(screen.getByRole('button', { name: 'Dictate' })).toBeTruthy()
    })

    it.each([
        ['bad_key', "'a b' is not --project: it must match [A-Z]+-?\\d*"],
        ['inside_run', 'CANOPY_RUN_ID is set: this runs inside one of canopy’s own ticks or runs'],
    ])('names the guard that refused it (%s), in place of the line, and stays on the page', async (guard, reason) => {
        answer = Response.json({ detail: { guard, reason } }, { status: 409 })
        const { router } = await renderForm(['web'])
        write(GOAL, 'a b')
        submit()
        expect((await screen.findByRole('alert')).textContent).toBe(`refused (${guard}): ${reason}`)
        expect(screen.queryByRole('status')).toBeNull()
        expect(router.state.location.pathname).toBe('/epics')
        expect(toasts).toEqual([])
    })
})
