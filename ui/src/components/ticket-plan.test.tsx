import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRouter, RouterContextProvider } from '@tanstack/react-router'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api } from '@/api/client'
import { keys } from '@/api/queries'
import type { PlanFile, PlanSummary, PlanThreadView, TicketPlans } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { PlanState, TicketPlan } from './ticket-plan'

const EARLIER: PlanSummary = {
    id: 1,
    run_id: 49,
    status: 'superseded',
    created_at: '2026-10-08T10:00:00Z',
    approved_at: null,
    approved_channel: null,
    approved_reason: null,
    effort: null,
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
    persona: null,
}
const PLANS: TicketPlans = {
    needed: true,
    policy: 'approve',
    setting: null,
    planning: null,
    changes_asked: null,
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

function renderPlan(plans: Partial<TicketPlans> = {}) {
    // Plan 1, which plan 2 replaces, already read: no test leaves a read of it in flight.
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } })
    client.setQueryData(keys.ticketPlan('ABC-1', 1), {
        ...NEWEST,
        plan: EARLIER,
        text: '# Plan\n\nAdd a CSV button.\n',
    })
    // The plan asks before the page is left, so it needs a router: one on the ticket's page, with nothing to load.
    const router = createRouter({
        routeTree: createRootRoute(),
        history: createMemoryHistory({ initialEntries: ['/tickets/ABC-1'] }),
    })
    return render(
        <QueryClientProvider client={client}>
            <RouterContextProvider router={router}>
                <TicketPlan ticketKey="ABC-1" plans={{ ...PLANS, ...plans }} />
            </RouterContextProvider>
        </QueryClientProvider>,
    )
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

// What the plan's page says of where the plan stands, as its description.
async function state(plans: Partial<TicketPlans>): Promise<string | null> {
    const { container } = await renderRouted(<PlanState plans={{ ...PLANS, ...plans }} />)
    return container.textContent
}

describe('TicketPlan', () => {
    describe('where it stands', () => {
        it('says the plan waits on you, in its panel’s header, and never that a waiting plan is not needed', () => {
            renderPlan({ needed: false, policy: 'off' })
            expect(screen.getByText('waiting on you')).toBeDefined()
            expect(screen.queryByText(/proposed|needed/u)).toBeNull()
        })

        it('says what the line under the actions says of the comments still open', () => {
            renderPlan({ threads: [THREAD, { ...THREAD, id: 10 }] })
            expect(
                screen.getByText(
                    '2 open comments go with Ask for changes. Approve sends them to the implement instead, and ' +
                        'resolves them.',
                ),
            ).toBeDefined()
        })

        it('says what Ask again sends once changes were asked for, not that the comments are still to go', () => {
            renderPlan({ threads: [THREAD], changes_asked: '2026-10-08T11:40:00Z' })
            expect(screen.getByText(/^Ask again sends the 1 open comment again\./u)).toBeDefined()
            expect(screen.queryByText(/goes with Ask for changes/u)).toBeNull()
        })

        it('says a planner comes next while there is no plan, and which run writes one', () => {
            const { unmount } = renderPlan({ newest: null, plans: [] })
            expect(screen.getByText('no plan yet: the next tick dispatches a planner')).toBeDefined()
            unmount()

            renderPlan({ newest: null, plans: [], planning: 51 })
            expect(screen.getByText('no plan yet: run 51 is writing one')).toBeDefined()
        })
    })

    describe('PlanState', () => {
        it('says who wrote a waiting plan, and that it waits on you', async () => {
            expect(await state({})).toBe(
                'Written by run:50. It waits on you: read it, comment, then approve it or ask for changes.',
            )
        })

        it('says what was approved, and how, and what changed in the file since', async () => {
            const approved = { ...PLAN, status: 'approved' as const, approved_at: '2026-10-08T11:30:00Z' }
            const newest = { ...NEWEST, plan: { ...approved, approved_channel: 'web' }, edited: true }
            expect(await state({ newest: { ...newest, changed_since_approval: true } })).toMatch(
                new RegExp(
                    '^Written by run:50, approved \\S+ ago via web, edited since the planner wrote it, changed since ' +
                        'it was approved\\. $',
                    'u',
                ),
            )
        })

        it('says the planner approved a plan it said needs no review, how much work it is, and why', async () => {
            const approved = {
                ...PLAN,
                status: 'approved' as const,
                approved_at: '2026-10-08T11:30:00Z',
                approved_channel: 'planner',
                approved_reason: 'A one-line typo fix in the README.',
                effort: 'small' as const,
            }
            expect(await state({ newest: { ...NEWEST, plan: approved } })).toMatch(
                new RegExp(
                    '^Written by run:50, approved \\S+ ago by the planner\\. Its planner judged it small work\\. ' +
                        'It said the plan needs no review: A one-line typo fix in the README\\.$',
                    'u',
                ),
            )
        })

        it('says which run writes the next plan, and leaves changes you asked for to their band', async () => {
            expect(await state({ planning: 51 })).toBe('Written by run:50. Run 51 is writing a new plan.')
            cleanup()
            expect(await state({ changes_asked: '2026-10-08T11:40:00Z' })).toBe('Written by run:50. ')
        })

        it('says a ticket that needs no plan needs none, and no planner for changes asked before', async () => {
            const superseded = { ...NEWEST, plan: { ...PLAN, status: 'superseded' as const } }
            expect(await state({ newest: superseded, needed: false, changes_asked: '2026-10-08T11:40:00Z' })).toBe(
                'Written by run:50. Its ticket needs no plan now.',
            )
        })

        it('says nothing with no plan, whose panel says what comes', async () => {
            expect(await state({ newest: null, plans: [] })).toBe('')
        })
    })

    it('says why the newest plan’s file cannot be shown, and where it is', () => {
        renderPlan({ newest: { ...NEWEST, text: null, problem: 'missing' } })
        expect(screen.getByText(`plan 2's file is missing: ${NEWEST.path}`)).toBeDefined()
        expect(screen.queryByRole('textbox', { name: 'Plan' })).toBeNull()
    })

    it('approves a proposed plan as canopy plan --approve does, and says so in its words', async () => {
        renderPlan()
        expect(button('Save').disabled).toBe(true)
        fireEvent.click(button('Approve'))
        // The line under the actions gives way to the approval's moment, which says it.
        expect((await screen.findByTestId('plan-approved')).textContent).toContain(
            'Plan 2 of ABC-1 is approved as its file stands now. The next tick can implement it.',
        )
        expect(sent).toEqual([{ method: 'POST', path: '/api/tickets/ABC-1/plan', body: { action: 'approve' } }])
    })

    it('marks an approval as the moment it is, with the way back to Attention, and never one refused', async () => {
        renderPlan()
        fireEvent.click(button('Approve'))
        const moment = await screen.findByTestId('plan-approved')
        expect(within(moment).getByRole('status').textContent).toBe(
            'Plan 2 of ABC-1 is approved as its file stands now. The next tick can implement it.',
        )
        expect(within(moment).getByRole('link', { name: 'Back to Attention' }).getAttribute('href')).toBe('/attention')
        cleanup()

        answers['POST /api/tickets/ABC-1/plan'] = Response.json(
            { detail: { guard: 'plan_not_proposed', reason: 'plan 2 is not proposed' } },
            { status: 409 },
        )
        renderPlan()
        fireEvent.click(button('Approve'))
        expect((await screen.findByRole('alert')).textContent).toBe(
            'refused (plan_not_proposed): plan 2 is not proposed',
        )
        expect(screen.queryByTestId('plan-approved')).toBeNull()
    })

    it('approves with notes: the note and open comments go to the implement, and the comments resolve', async () => {
        renderPlan({ threads: [THREAD] })
        fireEvent.change(screen.getByRole('textbox', { name: 'On the whole plan' }), {
            target: { value: 'Name the timezone.' },
        })
        fireEvent.click(button('Approve with notes'))
        // The line under the actions gives way to the approval's moment, which says it.
        expect((await screen.findByTestId('plan-approved')).textContent).toContain(
            'Plan 2 of ABC-1 is approved as its file stands now. The next tick can implement it. Your notes went ' +
                'with it, to its implement.',
        )
        const [approved, resolved] = sent
        expect(approved).toMatchObject({ method: 'POST', path: '/api/tickets/ABC-1/plan' })
        expect(approved?.body).toEqual({
            action: 'approve',
            message: expect.stringMatching(
                // The comment on its passage, then the note.
                /^Where I commented.*\n\n1\. On "CSV writer":\n.*On the whole plan:\nName the timezone\.$/su,
            ) as unknown,
        })
        expect(resolved).toEqual({
            method: 'PATCH',
            path: '/api/tickets/ABC-1/plan-threads/9',
            body: { resolved: true },
        })
    })

    describe("the plan's open decisions", () => {
        const DECIDING = [
            '# Plan',
            '',
            'Add the CSV writer.',
            '',
            '## Decisions',
            '',
            '### Decision 1: Which encoding the file is in',
            '',
            '- **A (chosen):** UTF-8, as the other exports are.',
            '- **B:** Latin-1, for the old spreadsheet.',
            '',
        ].join('\n')
        const ANSWER = 'Decision 1 (Which encoding the file is in): take B, not A.'

        function renderDeciding(plans: Partial<TicketPlans> = {}) {
            return renderPlan({ newest: { ...NEWEST, text: DECIDING }, ...plans })
        }

        it("offers each, the planner's choice picked, and sends nothing while it stays picked", async () => {
            renderDeciding()
            const decisions = screen.getByRole('region', { name: 'Open decisions' })
            const group = within(decisions).getByRole('radiogroup', {
                name: 'Decision 1: Which encoding the file is in',
            })
            const radios = within(group).getAllByRole<HTMLButtonElement>('radio')
            expect(radios.map((radio) => radio.getAttribute('aria-checked'))).toEqual(['true', 'false'])
            expect(within(group).getByRole('radio', { name: /^A: UTF-8.*the planner's choice/u })).toBe(radios[0])
            fireEvent.click(button('Approve'))
            await screen.findByTestId('plan-approved')
            expect(sent).toEqual([{ method: 'POST', path: '/api/tickets/ABC-1/plan', body: { action: 'approve' } }])
        })

        it('approves with another option picked as a note for the implement', async () => {
            renderDeciding()
            fireEvent.click(screen.getByRole('radio', { name: /^B: Latin-1/u }))
            expect(screen.getByText(/^1 answer goes with Approve, to the implement/u)).toBeDefined()
            fireEvent.click(button('Approve with notes'))
            await screen.findByTestId('plan-approved')
            expect(sent).toEqual([
                { method: 'POST', path: '/api/tickets/ABC-1/plan', body: { action: 'approve', message: ANSWER } },
            ])
        })

        it("asks for changes with another option picked, and picks the planner's again once asked", async () => {
            renderDeciding()
            fireEvent.click(screen.getByRole('radio', { name: /^B: Latin-1/u }))
            fireEvent.submit(screen.getByRole('form', { name: 'Ask for changes' }))
            await screen.findByRole('status')
            expect(sent).toEqual([
                {
                    method: 'POST',
                    path: '/api/tickets/ABC-1/replies',
                    body: expect.objectContaining({ body: ANSWER }) as unknown,
                },
            ])
            expect(screen.getByRole('radio', { name: /^A: UTF-8/u }).getAttribute('aria-checked')).toBe('true')
        })

        it('shows none for a plan that waits on no answer, or that asks none in their shape', () => {
            const approved = { ...PLAN, status: 'approved' as const }
            const { unmount } = renderDeciding({
                plans: [EARLIER, approved],
                newest: { ...NEWEST, text: DECIDING, plan: approved },
            })
            expect(screen.queryByRole('region', { name: 'Open decisions' })).toBeNull()
            unmount()
            renderPlan()
            expect(screen.queryByRole('radiogroup')).toBeNull()
        })
    })

    it('approves with nothing more while there are no notes', async () => {
        renderPlan()
        fireEvent.click(button('Approve'))
        await screen.findByTestId('plan-approved')
        expect(sent).toEqual([{ method: 'POST', path: '/api/tickets/ABC-1/plan', body: { action: 'approve' } }])
    })

    it('skips the plan as canopy plan --skip does, once asked in its place, Keep keeping it', () => {
        renderPlan()
        fireEvent.click(button('Skip the plan'))
        expect(screen.getByText('Skip the plan? Its implement goes ahead without it.')).toBeDefined()
        expect(document.activeElement).toBe(button('Keep'))
        fireEvent.keyDown(button('Keep'), { key: 'Escape' })
        expect(screen.queryByText(/^Skip the plan\?/u)).toBeNull()
        expect(button('Approve')).toBeDefined()
        expect(sent).toEqual([])
    })

    it('skips the plan as canopy plan --skip does', async () => {
        renderPlan()
        fireEvent.click(button('Skip the plan'))
        expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
        fireEvent.click(button('Skip the plan'))
        expect((await screen.findByRole('status')).textContent).toBe(
            "ABC-1's plan is skipped: its implement goes ahead without one.",
        )
        expect(sent).toEqual([{ method: 'POST', path: '/api/tickets/ABC-1/plan', body: { action: 'skip' } }])
    })

    it('offers no Approve for a plan approved and unchanged since, and says an edit needs approving again', () => {
        const approved = { ...PLAN, status: 'approved' as const, approved_at: '2026-10-08T11:30:00Z' }
        const { unmount } = renderPlan({ newest: { ...NEWEST, plan: approved } })
        expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
        expect(screen.getByText(/Saving an edit means approving it again\.$/u)).toBeDefined()
        unmount()

        renderPlan({ newest: { ...NEWEST, plan: approved, changed_since_approval: true } })
        expect(button('Approve')).toBeDefined()
    })

    it('keeps the plan read only while a planner writes a new one', () => {
        renderPlan({ planning: 51 })
        expect(screen.getByRole('textbox', { name: 'Plan' }).getAttribute('contenteditable')).toBe('false')
        expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
    })

    it('says an edit is unsaved, and saves it over the file as read, refused if the file changed', async () => {
        renderPlan()
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
        renderPlan()
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
        renderPlan()
        typeInPlan(' Then a test.')
        fireEvent.click(button('Save and approve'))
        expect((await screen.findByTestId('plan-approved')).textContent).toMatch(/^Plan 2 of ABC-1 is approved/u)
        expect(writes()).toEqual(['PUT /api/tickets/ABC-1/plans/2/file', 'POST /api/tickets/ABC-1/plan'])
    })

    it('asks the planner for changes with a reply, saving an edit first so the planner reads it', async () => {
        renderPlan()
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
        renderPlan({ threads: [THREAD] })
        const card = screen.getByRole('article', { name: 'Comment on “CSV writer”' })
        fireEvent.click(within(card).getByRole('button', { name: 'resolve' }))
        await waitFor(() => {
            expect(sent).toEqual([
                { method: 'PATCH', path: '/api/tickets/ABC-1/plan-threads/9', body: { resolved: true } },
            ])
        })
    })

    it('comments on a passage, and sends a change to that comment to the id the journal gives it', async () => {
        const release = holdAnswers()
        renderPlan()
        act(() => {
            editor().commands.setTextSelection({ from: 15, to: 25 })
        })
        fireEvent.click(button('Comment'))
        const draft = await screen.findByRole('form', { name: 'Comment' })
        fireEvent.change(within(draft).getByRole('textbox'), { target: { value: 'Which encoding?' } })
        fireEvent.submit(draft)

        const card = await screen.findByRole('article', { name: 'Comment on “CSV writer”' })
        fireEvent.click(within(card).getByRole('button', { name: 'resolve' }))
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
        renderPlan({ plans: [{ ...EARLIER, id: 0 }, EARLIER, PLAN] })
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
