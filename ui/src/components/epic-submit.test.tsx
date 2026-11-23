import { QueryClient } from '@tanstack/react-query'
import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { mockAttachmentLimits } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { Meta } from '@/api/types'
import { DictationContext } from '@/hooks/use-dictation'
import { ToastContext } from '@/hooks/use-toast'
import type { NewToast } from '@/lib/toasts'
import { renderRouted } from '@/test-utils'

import { EpicSubmitForm } from './epic-submit'

// What each submission sent, each upload after it, and what the server stand-in answers.
let sent: unknown[] = []
let uploads: { path: string; body: string }[] = []
let answer: Response | undefined
let uploadAnswer: ((name: string) => Response | undefined) | undefined
let toasts: NewToast[] = []

const server: Middleware = {
    async onRequest({ request }) {
        const path = new URL(request.url).pathname
        if (request.method === 'PUT') {
            const body = await request.text()
            uploads.push({ path, body })
            const name = path.split('/').at(-1) ?? ''
            return (
                uploadAnswer?.(name) ??
                Response.json({
                    attachment: { name, size: body.length, channel: 'web', added_at: '2026-10-08T12:00:00Z' },
                })
            )
        }
        if (request.method === 'POST' && path === '/api/epics') {
            sent.push(await request.json())
        }
        return answer ?? Response.json({ id: 4, repos: ['api', 'web'] })
    },
}

const GOAL = 'Let customers export their invoices as CSV.'

beforeEach(() => {
    sent = []
    uploads = []
    answer = undefined
    uploadAnswer = undefined
    toasts = []
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

/**
 * The form at `/epics`, in a workspace of `repos`, where the server offers dictation when `dictation` says so, and
 * holds attachments to `limits`.
 */
function renderForm(repos: string[], dictation = false, limits = mockAttachmentLimits) {
    const client = new QueryClient()
    const meta: Meta = {
        branch_urls: {},
        dictation,
        build: null,
        mock: false,
        ticket_url: null,
        version: '0.4.0',
        workspace_root: '/w',
        routers: [],
        attachment_limits: limits,
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

function choose(...files: File[]) {
    fireEvent.change(screen.getByLabelText('Files to attach to the epic'), { target: { files } })
}

// The files the form holds, by name, as its list shows them.
function held(): string[] {
    const list = screen.queryByRole('list', { name: 'Files to attach' })
    if (list === null) {
        return []
    }
    return within(list)
        .getAllByRole('listitem')
        .map((item) => item.textContent)
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

    it('holds the files chosen, each checked as it is, and attaches them once the epic is recorded', async () => {
        const { router } = await renderForm(['web'])
        write(GOAL)
        choose(new File(['# Spec\n'], 'Invoice spec (v2).md'), new File(['a,b\n'], 'fields.csv'))
        await waitFor(() => {
            expect(held()).toEqual(['Invoice-spec-v2.md7 bytes', 'fields.csv4 bytes'])
        })
        fireEvent.click(screen.getByRole('button', { name: 'Drop fields.csv' }))
        expect(held()).toEqual(['Invoice-spec-v2.md7 bytes'])
        // Neither file control submits the form it sits in.
        fireEvent.click(screen.getByRole('button', { name: /Attach a file/u }))
        expect(sent).toEqual([])
        submit()
        await waitFor(() => {
            expect(router.state.location.pathname).toBe('/epics/4')
        })
        expect(sent).toHaveLength(1)
        expect(uploads).toEqual([{ path: '/api/epics/4/attachments/Invoice-spec-v2.md', body: '# Spec\n' }])
        expect(toasts).toEqual([
            {
                title: 'Submitted epic:4 with Invoice-spec-v2.md; the next tick starts its plan run.',
                detail: 'over api, web',
                tone: 'done',
            },
        ])
    })

    it.each([
        [
            'a file that is not text',
            [new File([new Uint8Array([37, 80, 68, 70, 255, 254])], 'spec.pdf')],
            mockAttachmentLimits,
            'refused (not_text): spec.pdf is not UTF-8 text; export it as Markdown or plain text',
        ],
        ['a blank file', [new File([' \n\t'], 'blank.md')], mockAttachmentLimits, 'refused (empty): blank.md is empty'],
        [
            'a file holding a NUL',
            [new File(['a\0b'], 'nul.txt')],
            mockAttachmentLimits,
            'refused (not_text): nul.txt holds a NUL byte, so it is not plain text',
        ],
        [
            'a name it holds',
            [new File(['one'], 'spec.md'), new File(['two'], 'spec.md')],
            mockAttachmentLimits,
            'refused (taken): the epic already has an attachment named spec.md; remove it first, or rename the file',
        ],
        [
            'one past the count',
            [new File(['one'], 'a.md'), new File(['two'], 'b.md')],
            { ...mockAttachmentLimits, max_files: 1 },
            'refused (too_many): the epic has 1 attachments, the most it may hold; remove one first',
        ],
        [
            'one past the total',
            [new File(['12345'], 'a.md'), new File(['67890'], 'b.md')],
            { ...mockAttachmentLimits, max_total_bytes: 8 },
            "refused (too_large): the epic's attachments would hold 10 bytes, over the 8 bytes they may together",
        ],
    ])(
        'refuses %s as it is chosen, in the words the server would, and holds the rest',
        async (_, files, limits, said) => {
            await renderForm(['web'], false, limits)
            choose(...files)
            expect((await screen.findByRole('alert')).textContent).toBe(said)
            expect(held()).toHaveLength(files.length - 1)
            expect(uploads).toEqual([])
        },
    )

    it('holds the files after a refused one, and says the refusal over an earlier failed submission', async () => {
        answer = Response.json({ detail: { guard: 'bad_key', reason: "'a b' is not --project" } }, { status: 409 })
        await renderForm(['web'])
        write(GOAL, 'a b')
        submit()
        expect((await screen.findByRole('alert')).textContent).toBe("refused (bad_key): 'a b' is not --project")
        choose(new File([''], 'empty.md'), new File(['kept'], 'kept.md'))
        await waitFor(() => {
            expect(screen.getByRole('alert').textContent).toBe('refused (empty): empty.md is empty')
        })
        expect(held()).toEqual(['kept.md4 bytes'])
    })

    it('neither submits nor takes more files while chosen ones are read', async () => {
        await renderForm(['web'])
        write(GOAL)
        const read: { done?: (bytes: ArrayBuffer) => void } = {}
        const slow = new File(['# Spec\n'], 'spec.md')
        slow.arrayBuffer = () =>
            new Promise((resolve) => {
                read.done = resolve
            })
        choose(slow)
        await waitFor(() => {
            expect(submitButton().disabled).toBe(true)
        })
        expect(screen.getByRole<HTMLButtonElement>('button', { name: /Attach a file/u }).disabled).toBe(true)
        read.done?.(new TextEncoder().encode('# Spec\n').buffer)
        await waitFor(() => {
            expect(submitButton().disabled).toBe(false)
        })
        expect(held()).toEqual(['spec.md7 bytes'])
    })

    it('says a file may have been attached when the server failed rather than refused it', async () => {
        uploadAnswer = () => new Response(null, { status: 502 })
        await renderForm(['web'])
        write(GOAL)
        choose(new File(['one'], 'a.md'))
        await waitFor(() => {
            expect(held()).toHaveLength(1)
        })
        submit()
        await waitFor(() => {
            expect(toasts).toHaveLength(1)
        })
        expect(toasts[0]?.title).toBe(
            'Submitted epic:4, but a.md may not have been attached: check its page before the next tick.',
        )
    })

    it('offers no files where attaching is off', async () => {
        await renderForm(['web'], false, { ...mockAttachmentLimits, max_files: 0 })
        expect(screen.queryByRole('button', { name: /Attach a file/u })).toBeNull()
    })

    it('opens the epic when the server refuses a file, and the toast names it to attach there', async () => {
        uploadAnswer = (name) =>
            name === 'b.md'
                ? Response.json({ detail: { guard: 'too_large', reason: 'b.md is over the 1 KiB' } }, { status: 409 })
                : undefined
        const { router } = await renderForm(['web'])
        write(GOAL)
        choose(new File(['one'], 'a.md'), new File(['two'], 'b.md'), new File(['three'], 'c.md'))
        await waitFor(() => {
            expect(held()).toHaveLength(3)
        })
        submit()
        await waitFor(() => {
            expect(router.state.location.pathname).toBe('/epics/4')
        })
        // The one after it is still sent.
        expect(uploads.map((u) => u.path.split('/').at(-1))).toEqual(['a.md', 'b.md', 'c.md'])
        expect(toasts).toEqual([
            {
                title:
                    'Submitted epic:4 with 2 files, but b.md was not attached: ' +
                    'attach it on its page before the next tick.',
                detail: 'refused (too_large): b.md is over the 1 KiB',
                tone: 'failed',
            },
        ])
    })
})
