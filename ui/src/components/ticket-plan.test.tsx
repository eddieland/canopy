import { QueryClient } from '@tanstack/react-query'
import { act, cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { keys } from '@/api/queries'
import type { PlanFile, PlanSummary, PlanThreadView, TicketPlans } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { TicketPlan } from './ticket-plan'

const EARLIER: PlanSummary = {
    id: 1,
    run_id: 49,
    status: 'superseded',
    created_at: '2026-10-08T10:00:00Z',
    approved_at: null,
    approved_channel: null,
}
const PLAN: PlanSummary = { ...EARLIER, id: 2, run_id: 50, status: 'proposed', created_at: '2026-10-08T11:00:00Z' }
const TEXT = '# Plan\n\nAdd the CSV writer.\n'
const NEWEST: PlanFile = {
    plan: PLAN,
    text: TEXT,
    path: '/home/op/.canopy/plans/ABC-1/2.md',
    problem: null,
    sha256: 'read-hash',
    edited: false,
    changed_since_approval: false,
}
const PLANS: TicketPlans = {
    needed: true,
    policy: 'approve',
    setting: null,
    planning: null,
    threads: [],
    plans: [EARLIER, PLAN],
    newest: NEWEST,
}
const THREAD: PlanThreadView = {
    id: 9,
    quote: 'CSV writer',
    prefix: 'Add the ',
    suffix: '.',
    body: 'Which encoding?',
    at: '2026-10-08T11:10:00Z',
    resolved: false,
    replies: [],
}

// Every write the plan sends, by method and path, and what the server stand-in answers each; every read, which
// answers plan 0, the one plan not already in the client.
let sent: { method: string; path: string; body: unknown }[] = []
let read: string[] = []
let answers: Record<string, Response> = {}
let hold: Promise<void> = Promise.resolve()

const server: Middleware = {
    async onRequest({ request }) {
        const path = new URL(request.url).pathname
        if (request.method === 'GET') {
            read.push(path)
            return Response.json({ ...NEWEST, plan: { ...EARLIER, id: 0 }, text: '# Plan\n\nShow the CSV.\n' })
        }
        const text = await request.text()
        sent.push({ method: request.method, path, body: text ? (JSON.parse(text) as unknown) : undefined })
        await hold
        return answers[`${request.method} ${path}`] ?? Response.json(answer(request.method, path, text))
    },
}

// What the server says to each write, as the CLI's code would.
function answer(method: string, path: string, text: string): unknown {
    if (path.endsWith('/plan')) {
        const { action } = JSON.parse(text) as { action: string }
        return { action, already: false, plan: 2, superseded: null }
    }
    if (path.endsWith('/file')) {
        return { sha256: 'new-hash', size: 40 }
    }
    if (path.endsWith('/replies')) {
        return { message_id: 6, answers: null, new: true }
    }
    if (method === 'POST' && path.endsWith('/plan-threads')) {
        return { ...THREAD, id: 31, ...(JSON.parse(text) as object), replies: [] }
    }
    return THREAD
}

beforeEach(() => {
    sent = []
    read = []
    answers = {}
    hold = Promise.resolve()
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
})

// Holds the server stand-in's answers until the function returned is called.
function holdAnswers(): () => void {
    let release: (() => void) | undefined
    hold = new Promise((resolve) => {
        release = resolve
    })
    return () => release?.()
}

function renderPlan(plans: Partial<TicketPlans> = {}): ReturnType<typeof renderRouted> {
    // Plan 1, which plan 2 replaces, already read: no test leaves a read of it in flight.
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } })
    client.setQueryData(keys.ticketPlan('ABC-1', 1), {
        ...NEWEST,
        plan: EARLIER,
        text: '# Plan\n\nAdd a CSV button.\n',
    })
    // Under a router: the plan asks before the page is left with work unsaved, through the router's blocker.
    return renderRouted(<TicketPlan ticketKey="ABC-1" plans={{ ...PLANS, ...plans }} />, { client })
}

// The plan's editor, through the handle Tiptap leaves on it for tests: an edit there is the operator typing.
interface EditorElement extends HTMLElement {
    editor?: {
        commands: {
            insertContentAt: (position: number, text: string) => boolean
            setTextSelection: (range: { from: number; to: number }) => boolean
        }
    }
}

function editor() {
    const element: EditorElement = screen.getByRole('textbox', { name: 'Plan' })
    if (element.editor === undefined) {
        throw new Error('no editor on the plan')
    }
    return element.editor
}

// Types `text` at the end of the plan's paragraph, as the operator would.
function typeInPlan(text: string) {
    act(() => {
        // The heading `Plan` takes positions 0 to 6, and the paragraph's 19 characters start at 7.
        editor().commands.insertContentAt(26, text)
    })
}

function button(name: string): HTMLButtonElement {
    return screen.getByRole('button', { name })
}

function writes(): string[] {
    return sent.map((request) => `${request.method} ${request.path}`)
}

describe('TicketPlan', () => {
    describe('its status line', () => {
        it('says why the ticket needs a plan, and its newest plan’s status', async () => {
            await renderPlan()
            const status = screen.getByTestId('plan-status')
            expect(status.textContent).toMatch(
                /^Plan needed, by policy\.plan approve\.proposedplan 2, written \S+ ago$/u,
            )
        })

        it('says when the operator’s own word decides, and what was approved, edited, and changed since', async () => {
            const approved = { ...PLAN, status: 'approved' as const, approved_at: '2026-10-08T11:30:00Z' }
            await renderPlan({
                setting: 'plan',
                newest: {
                    ...NEWEST,
                    plan: { ...approved, approved_channel: 'web' },
                    edited: true,
                    changed_since_approval: true,
                },
            })
            expect(screen.getByTestId('plan-status').textContent).toMatch(
                new RegExp(
                    '^Plan needed, by your word, plan\\.approvedplan 2, written \\S+ ago, approved \\S+ ago via web, ' +
                        'edited since the planner wrote it, changed since it was approved$',
                    'u',
                ),
            )
        })

        it('says a planner comes next while there is no plan, and which run writes one', async () => {
            const { unmount } = await renderPlan({ newest: null, plans: [] })
            expect(screen.getByText('None yet: the next tick dispatches a planner.')).toBeDefined()
            unmount()

            await renderPlan({ newest: null, plans: [], planning: 51 })
            expect(screen.getByText('Run 51 is writing a new plan.')).toBeDefined()
            expect(screen.queryByText(/^None yet/u)).toBeNull()
        })
    })

    it('says why the newest plan’s file cannot be shown, and where it is', async () => {
        await renderPlan({ newest: { ...NEWEST, text: null, problem: 'missing' } })
        expect(screen.getByText(`plan 2's file is missing: ${NEWEST.path}`)).toBeDefined()
        expect(screen.queryByRole('textbox', { name: 'Plan' })).toBeNull()
    })

    it('approves a proposed plan as canopy plan --approve does, and says so in its words', async () => {
        await renderPlan()
        expect(button('Save').disabled).toBe(true)
        fireEvent.click(button('Approve'))
        expect((await screen.findByRole('status')).textContent).toBe(
            'Plan 2 of ABC-1 is approved as its file stands now. The next tick can implement it.',
        )
        expect(sent).toEqual([{ method: 'POST', path: '/api/tickets/ABC-1/plan', body: { action: 'approve' } }])
    })

    it('skips the plan as canopy plan --skip does', async () => {
        await renderPlan()
        fireEvent.click(button('Skip the plan'))
        expect((await screen.findByRole('status')).textContent).toBe(
            "ABC-1's plan is skipped: its implement goes ahead without one.",
        )
        expect(sent).toEqual([{ method: 'POST', path: '/api/tickets/ABC-1/plan', body: { action: 'skip' } }])
    })

    it('offers no Approve for a plan approved and unchanged since, and says an edit needs approval again', async () => {
        const approved = { ...PLAN, status: 'approved' as const, approved_at: '2026-10-08T11:30:00Z' }
        const { unmount } = await renderPlan({ newest: { ...NEWEST, plan: approved } })
        expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
        expect(screen.getByText(/Saving an edit means approving it again\.$/u)).toBeDefined()
        unmount()

        await renderPlan({ newest: { ...NEWEST, plan: approved, changed_since_approval: true } })
        expect(button('Approve')).toBeDefined()
    })

    it('keeps the plan read only while a planner writes a new one', async () => {
        await renderPlan({ planning: 51 })
        expect(screen.getByRole('textbox', { name: 'Plan' }).getAttribute('contenteditable')).toBe('false')
        expect(screen.getByText('Run 51 is writing a new plan.')).toBeDefined()
    })

    it('says an edit is unsaved, and saves it over the file as read, refused if the file changed', async () => {
        await renderPlan()
        typeInPlan(' Then a test.')
        expect(screen.getByText('Unsaved edits')).toBeDefined()
        expect(button('Save and approve')).toBeDefined()
        expect(button('Save').title).toBe('Save (Ctrl+S)')

        fireEvent.click(button('Save'))
        expect((await screen.findByRole('status')).textContent).toBe('Saved the plan.')
        expect(sent).toEqual([
            {
                method: 'PUT',
                path: '/api/tickets/ABC-1/plans/2/file',
                body: { markdown: '# Plan\n\nAdd the CSV writer. Then a test.', read_sha256: 'read-hash' },
            },
        ])

        answers['PUT /api/tickets/ABC-1/plans/2/file'] = Response.json(
            { detail: { guard: 'bad_plan', reason: 'the file changed since it was read' } },
            { status: 409 },
        )
        await waitFor(() => {
            expect(button('Save').disabled).toBe(false)
        })
        fireEvent.click(button('Save'))
        expect((await screen.findByRole('alert')).textContent).toBe(
            'refused (bad_plan): the file changed since it was read',
        )
    })

    it('saves with Ctrl+S anywhere on the page, and only once there is an edit', async () => {
        await renderPlan()
        const unsaved = new KeyboardEvent('keydown', { key: 's', ctrlKey: true, cancelable: true })
        document.dispatchEvent(unsaved)
        expect(unsaved.defaultPrevented).toBe(true)
        expect(sent).toEqual([])

        typeInPlan(' Then a test.')
        fireEvent.keyDown(document, { key: 's', ctrlKey: true })
        expect((await screen.findByRole('status')).textContent).toBe('Saved the plan.')
        expect(writes()).toEqual(['PUT /api/tickets/ABC-1/plans/2/file'])
    })

    it('saves an edit before approving, so the approval takes the plan as edited', async () => {
        await renderPlan()
        typeInPlan(' Then a test.')
        fireEvent.click(button('Save and approve'))
        expect((await screen.findByRole('status')).textContent).toMatch(/^Plan 2 of ABC-1 is approved/u)
        expect(writes()).toEqual(['PUT /api/tickets/ABC-1/plans/2/file', 'POST /api/tickets/ABC-1/plan'])
    })

    it('asks the planner for changes with a reply, saving an edit first so the planner reads it', async () => {
        await renderPlan()
        typeInPlan(' Then a test.')
        const ask = screen.getByRole('form', { name: 'Ask for changes' })
        fireEvent.change(within(ask).getByRole('textbox', { name: 'On the whole plan' }), {
            target: { value: 'Split it in two.' },
        })
        fireEvent.submit(ask)

        expect((await screen.findByRole('status')).textContent).toBe(
            'Recorded message 6 on ABC-1: the next tick asks the planner for a new plan with your comments.',
        )
        expect(writes()).toEqual(['PUT /api/tickets/ABC-1/plans/2/file', 'POST /api/tickets/ABC-1/replies'])
        expect(sent[1]?.body).toMatchObject({ body: expect.stringMatching(/^Split it in two\./u) as unknown })
    })

    it('saves a change to a comment as it is made', async () => {
        await renderPlan({ threads: [THREAD] })
        const card = screen.getByRole('article', { name: 'Comment on “CSV writer”' })
        fireEvent.click(within(card).getByRole('button', { name: 'Resolve' }))
        await waitFor(() => {
            expect(sent).toEqual([
                { method: 'PATCH', path: '/api/tickets/ABC-1/plan-threads/9', body: { resolved: true } },
            ])
        })
    })

    it('comments on a passage, and sends a change to that comment to the id the journal gives it', async () => {
        const release = holdAnswers()
        await renderPlan()
        act(() => {
            editor().commands.setTextSelection({ from: 15, to: 25 })
        })
        fireEvent.click(button('Comment'))
        const draft = await screen.findByRole('form', { name: 'Comment' })
        fireEvent.change(within(draft).getByRole('textbox'), { target: { value: 'Which encoding?' } })
        fireEvent.submit(draft)

        const card = await screen.findByRole('article', { name: 'Comment on “CSV writer”' })
        fireEvent.click(within(card).getByRole('button', { name: 'Resolve' }))
        release()
        await waitFor(() => {
            expect(writes()).toEqual([
                'POST /api/tickets/ABC-1/plan-threads',
                'PATCH /api/tickets/ABC-1/plan-threads/31',
            ])
        })
        expect(sent[0]?.body).toMatchObject({ quote: 'CSV writer', suffix: '.', body: 'Which encoding?' })
    })

    it('lists the earlier plans, newest first, each read only once opened', async () => {
        await renderPlan({ plans: [{ ...EARLIER, id: 0 }, EARLIER, PLAN] })
        const shows = screen.getAllByRole('button', { name: /^Show plan/u }).map((show) => show.textContent)
        expect(shows).toEqual(['Show plan 1', 'Show plan 0'])
        expect(screen.getAllByRole('textbox', { name: 'Plan' })).toHaveLength(1)
        expect(read).toEqual([])

        fireEvent.click(button('Show plan 0'))
        await waitFor(() => {
            expect(screen.getAllByRole('textbox', { name: 'Plan' })).toHaveLength(2)
        })
        expect(read).toEqual(['/api/tickets/ABC-1/plans/0'])
        const opened = screen.getAllByRole('textbox', { name: 'Plan' })[1]
        expect(opened?.textContent).toBe('PlanShow the CSV.')
        expect(opened?.getAttribute('contenteditable')).toBe('false')
    })
})
