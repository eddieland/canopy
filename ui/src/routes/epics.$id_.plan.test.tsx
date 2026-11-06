import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import type { AnyRouter } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { mockEpicDetails, mockEpicPlans } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { EpicDetail, EpicPlans } from '@/api/types'

import { Route } from './epics.$id_.plan'

// Half an hour after the mock journal's T0, as the screenshots are taken.
const NOW = new Date('2026-10-08T12:30:00Z')

// What the server stand-in answers, by `METHOD path`, and what was sent to it. Every epic the mocks hold is read
// already, so a read that reaches it asks for one canopy has not, or reads one again after a write, which finds the
// mocks as they were unless a test answers otherwise.
let answers: Record<string, () => Response> = {}
let sent: { method: string; path: string; body: unknown }[] = []
const server: Middleware = {
    async onRequest({ request }) {
        const path = new URL(request.url).pathname
        const body: unknown = request.method === 'POST' ? await request.json() : undefined
        sent.push({ method: request.method, path, body })
        const answer = answers[`${request.method} ${path}`]
        return answer === undefined ? Response.json({ detail: 'no such epic' }, { status: 404 }) : answer()
    },
}

beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(NOW)
    answers = Object.fromEntries(
        mockEpicDetails.flatMap((detail) => [
            [`GET /api/epics/${detail.epic.id}`, () => Response.json(detail)],
            [`GET /api/epics/${detail.epic.id}/plans`, () => Response.json(plansOf(detail.epic.id))],
        ]),
    )
    sent = []
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
    vi.useRealTimers()
})

/** `plans` as read again once their newest is approved. */
function approvedPlans(plans: EpicPlans): EpicPlans {
    const newest = plans.plans.at(-1)
    if (newest === undefined) {
        throw new Error('no plan to approve')
    }
    const plan = {
        ...newest.plan,
        status: 'approved' as const,
        approved_at: NOW.toISOString(),
        approved_channel: 'web',
    }
    return { ...plans, plans: [...plans.plans.slice(0, -1), { ...newest, plan }] }
}

/** The mock plans of epic `id`, with `fields` over them. */
function plansOf(id: number, fields: Partial<EpicPlans> = {}): EpicPlans {
    const found = mockEpicPlans.find((plans) => plans.epic_id === id)
    if (found === undefined) {
        throw new Error(`no mock plans of epic:${String(id)}`)
    }
    return { ...found, ...fields }
}

/**
 * The plan page of epic `id`, every mock epic and its plans already read, `plans` in place of the mocks' where given.
 * Nothing is stale, so only a query the page starts that has no data reads the server, which answers that it has no
 * such epic; what the shell's parts read is read already.
 */
async function renderPage(
    id: string,
    plans: EpicPlans[] = mockEpicPlans,
    details: EpicDetail[] = mockEpicDetails,
): Promise<void> {
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
    client.setQueryData(keys.attention, [])
    client.setQueryData(keys.tick, { tick: null, acknowledged: null })
    client.setQueryData(keys.meta, {})
    for (const detail of details) {
        client.setQueryData(keys.epic(detail.epic.id), detail)
    }
    for (const shown of plans) {
        client.setQueryData(keys.epicPlans(shown.epic_id), shown)
    }
    const root = createRootRoute()
    const page = Route.update({ id: '/epics/$id_/plan', path: '/epics/$id/plan', getParentRoute: () => root } as never)
    const router = createRouter({
        routeTree: root.addChildren([page]),
        history: createMemoryHistory({ initialEntries: [`/epics/${id}/plan`] }),
    })
    await router.load()
    render(
        <QueryClientProvider client={client}>
            <RouterProvider router={router as AnyRouter} />
        </QueryClientProvider>,
    )
}

/** The page's description, under its title. */
function description(): string {
    const title = screen.getByRole('heading', { level: 1 })
    return title.closest('header')?.querySelector('p')?.textContent ?? ''
}

describe("an epic's plan page", () => {
    it('heads it plan, under its epic, with its goal', async () => {
        await renderPage('1')
        const title = await screen.findByRole('heading', { level: 1 })
        expect(title.textContent).toBe(
            'plan Move billing to the v2 API everywhere it is called, web and mobile both, ' +
                'and retire v1 once nothing reads it.',
        )
        const trail = screen.getByRole('navigation', { name: 'Breadcrumb' })
        expect(within(trail).getByRole('link', { name: 'epic:1' }).getAttribute('href')).toBe('/epics/1')
    })

    it('shows the newest plan read only, its status, its run, its hash, and when, with no comments', async () => {
        await renderPage('1')
        const plan = await screen.findByRole('textbox', { name: 'Plan' })
        expect(plan.textContent).toContain('Every billing call goes to v2')
        expect(plan.getAttribute('contenteditable')).toBe('false')
        const header = within(screen.getByTestId('epic-plan')).getAllByRole('heading', { level: 2 })[0]
        expect(header?.textContent).toBe('Plan')
        expect(within(screen.getByTestId('epic-plan')).getByText('approved')).toBeTruthy()
        expect(screen.getByTestId('epic-plan').textContent).toContain('12h ago')
        expect(description()).toBe('Written by epic:1#1, approved 10h ago via web.')
        expect(screen.getByTestId('plan-hash').textContent).toBe('sha2569f2c4e81b07d')
        expect(screen.queryByRole('heading', { name: 'Comments' })).toBeNull()
        expect(screen.queryByRole('button', { name: /^Comment/u })).toBeNull()
        expect(screen.queryByTestId('earlier-plans')).toBeNull()
    })

    it('says a proposed plan waits on you, and marks what changed since the plan it replaces', async () => {
        await renderPage('2')
        const plan = await screen.findByRole('textbox', { name: 'Plan' })
        expect(plan.textContent).toContain('the copy goes when its customer does')
        expect(within(screen.getByTestId('epic-plan')).getByText('waiting on you')).toBeTruthy()
        expect(description()).toBe('Written by epic:2#3. It waits on you: approve it, or ask for changes.')
        const changes = screen.getByRole('button', { name: 'Changes since plan 2' })
        expect(changes.getAttribute('aria-pressed')).toBe('true')
    })

    it("offers a stopped epic's waiting plan for approval, and no reply, which it takes none of", async () => {
        const proposed = mockEpicDetails.find((detail) => detail.epic.id === 2)
        if (proposed === undefined) {
            throw new Error('no mock epic:2')
        }
        const epic = { ...proposed.epic, standing: 'stopped' as const, stopped_at: NOW.toISOString() }
        const stopped = [...mockEpicDetails.filter((detail) => detail !== proposed), { ...proposed, epic }]
        await renderPage('2', mockEpicPlans, stopped)
        await screen.findByRole('textbox', { name: 'Plan' })
        expect(screen.getByRole('button', { name: 'Approve' })).toBeTruthy()
        expect(screen.queryByRole('button', { name: 'Ask for changes' })).toBeNull()
        expect(description()).toBe(
            'Written by epic:2#3. You stopped the epic: you may still approve it, but no plan run starts for changes.',
        )
    })

    it('approves a plan that waits by the hash the page read, and marks the moment in the CLI words', async () => {
        const approved = plansOf(2)
        answers['POST /api/epics/2/plan/approval'] = () => Response.json({ plan: 3, run_id: 3, change: null })
        answers['GET /api/epics/2/plans'] = () => Response.json(approvedPlans(approved))
        await renderPage('2')
        fireEvent.click(await screen.findByRole('button', { name: 'Approve' }))
        const moment = await screen.findByTestId('plan-approved')
        expect(within(moment).getByRole('status').textContent).toBe("Approved epic:2's plan, written by run 3.")
        expect(sent[0]).toEqual({
            method: 'POST',
            path: '/api/epics/2/plan/approval',
            body: { read_sha256: approved.plans.at(-1)?.sha256 },
        })
        // Read again, it waits on no one: its actions go, and what the approval did stays.
        await waitFor(() => expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull())
        expect(within(screen.getByTestId('epic-plan')).getByText('approved')).toBeTruthy()
        expect(screen.getByTestId('plan-approved')).toBeTruthy()
        expect(screen.queryByRole('button', { name: 'Ask for changes' })).toBeNull()
    })

    it.each([
        ['stale', "epic:2's plan file changed since you read it; read it again to approve it"],
        ['bad_outline', "epic:2's plan cannot be read: R1 appears twice"],
        ['reused_id', 'the plan uses B4, which an earlier approved plan dropped: never again'],
    ])('says an approval refused %s, naming its guard, and marks no moment', async (guard, reason) => {
        answers['POST /api/epics/2/plan/approval'] = () => Response.json({ detail: { guard, reason } }, { status: 409 })
        await renderPage('2')
        fireEvent.click(await screen.findByRole('button', { name: 'Approve' }))
        expect((await screen.findByRole('alert')).textContent).toBe(`refused (${guard}): ${reason}`)
        expect(screen.queryByTestId('plan-approved')).toBeNull()
        expect(screen.getByRole('button', { name: 'Approve' })).toBeTruthy()
    })

    it.each([
        [{}, 'Recorded message 21 on epic:2. The next tick starts its next plan run, which reads your reply.'],
        [
            { running_run: 5 },
            'Recorded message 21 on epic:2. Its plan run is still working; the first tick after it ends starts the ' +
                'next, with your reply.',
        ],
        [
            { plan_runs: 3 },
            'Recorded message 21 on epic:2. It has had 3 plan runs, policy.max_plan_attempts; none starts again for ' +
                'this reply.',
        ],
    ])('asks for changes as a reply, and says what it starts', async (fields, said) => {
        answers['POST /api/epics/2/replies'] = () =>
            Response.json({
                message_id: 21,
                new: true,
                running_run: null,
                plan_runs: 2,
                max_plan_attempts: 3,
                ...fields,
            })
        await renderPage('2')
        fireEvent.change(await screen.findByRole('textbox', { name: 'On the whole plan' }), {
            target: { value: 'Say how the copy clears offline.' },
        })
        // A note goes only with Ask for changes: Approve would leave it unsent.
        expect(screen.getByRole('button', { name: 'Approve' }).hasAttribute('disabled')).toBe(true)
        fireEvent.click(screen.getByRole('button', { name: 'Ask for changes' }))
        expect((await screen.findByText(/^Recorded message 21/u)).textContent).toBe(said)
        expect(sent.find((request) => request.method === 'POST')).toEqual({
            method: 'POST',
            path: '/api/epics/2/replies',
            body: { body: 'Say how the copy clears offline.', submission: expect.any(String) as unknown },
        })
        expect(screen.queryByTestId('plan-approved')).toBeNull()
    })

    it('says a reply refused, naming its guard', async () => {
        answers['POST /api/epics/2/replies'] = () =>
            Response.json({ detail: { guard: 'inside_run', reason: 'run 7 is not the operator' } }, { status: 409 })
        await renderPage('2')
        fireEvent.change(await screen.findByRole('textbox', { name: 'On the whole plan' }), {
            target: { value: 'Again.' },
        })
        fireEvent.click(screen.getByRole('button', { name: 'Ask for changes' }))
        expect((await screen.findByRole('alert')).textContent).toBe('refused (inside_run): run 7 is not the operator')
    })

    it('heads a plan whose changes you asked with the band, and asks again', async () => {
        await renderPage('2', [plansOf(2, { changes_asked: '2026-10-08T12:20:00Z' })])
        const band = await screen.findByTestId('changes-asked')
        expect(band.textContent).toBe(
            'You asked for changes 10m ago: the next tick starts its next plan run, which reads your reply.',
        )
        expect(within(screen.getByTestId('epic-plan')).getByText('changes asked')).toBeTruthy()
        expect(description()).toBe('Written by epic:2#3.')
        // The plan still waits: approving it before the next run starts is your later word.
        expect(screen.getByRole('button', { name: 'Approve' })).toBeTruthy()
        expect(screen.getByRole('button', { name: 'Ask again' })).toBeTruthy()
    })

    it('offers no word on a plan while a plan run writes the next, nor on an approved one', async () => {
        await renderPage('2', [plansOf(2, { planning: 9, changes_asked: '2026-10-08T12:20:00Z' })])
        await screen.findByRole('textbox', { name: 'Plan' })
        expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
        expect(screen.queryByTestId('changes-asked')).toBeNull()
        cleanup()
        await renderPage('1')
        await screen.findByRole('textbox', { name: 'Plan' })
        expect(screen.queryByTestId('plan-bar')).toBeNull()
    })

    it('folds the earlier plans, newest first, each read only once opened', async () => {
        const [first, second] = plansOf(2).plans
        if (first === undefined || second === undefined) {
            throw new Error('epic 2 has two plans')
        }
        // A third plan, so the order shows: plan 3, then plan 2, under the newest.
        const third = { ...second, plan: { ...second.plan, status: 'superseded' as const } }
        const newest = { ...second, plan: { ...second.plan, id: 4, run_id: 5 } }
        await renderPage('2', [plansOf(2, { plans: [first, third, newest] })])
        const earlier = await screen.findByTestId('earlier-plans')
        const opens = within(earlier).getAllByRole('button', { name: /^Show plan/u })
        expect(opens.map((button) => button.textContent)).toEqual(['Show plan 3', 'Show plan 2'])
        expect(within(earlier).queryByRole('textbox')).toBeNull()
        const [, older] = opens
        if (older === undefined) {
            throw new Error('two earlier plans')
        }
        fireEvent.click(older)
        const opened = await within(earlier).findByRole('textbox', { name: 'Plan' })
        expect(opened.textContent).toContain('Sync on launch and on pull to refresh only.')
        expect(opened.getAttribute('contenteditable')).toBe('false')
        expect(within(earlier).queryByRole('heading', { name: 'Comments' })).toBeNull()
    })

    it('says why a plan whose file does not read shows nothing', async () => {
        const [only] = plansOf(1).plans
        if (only === undefined) {
            throw new Error('epic 1 has a plan')
        }
        const gone = { ...only, text: null, problem: 'missing', sha256: null }
        await renderPage('1', [plansOf(1, { plans: [gone] })])
        expect((await screen.findByText(/file is missing/u)).textContent).toBe(
            "plan 1's file is missing: .canopy/plans/epics/1/run-1.md",
        )
        expect(screen.queryByRole('textbox', { name: 'Plan' })).toBeNull()
        expect(description()).toBe('Written by epic:1#1, approved 10h ago via web.')
        expect(screen.queryByTestId('plan-hash')).toBeNull()
    })

    it('names the plan run at work on an epic with no plan yet', async () => {
        await renderPage('3')
        expect((await screen.findByTestId('plan-run-working')).textContent).toContain('epic:3#4 is writing its plan')
        expect(screen.queryByRole('textbox', { name: 'Plan' })).toBeNull()
    })

    it('says an epic canopy has no record of is missing', async () => {
        await renderPage('9')
        expect((await screen.findByText('canopy has no epic:9')).textContent).toBe('canopy has no epic:9')
        expect(screen.queryByTestId('epic-plan')).toBeNull()
    })

    it.each(['abc', '0'])('names no epic at %s', async (id) => {
        await renderPage(id)
        expect((await screen.findByText(`canopy has no epic:${id}`)).textContent).toBe(`canopy has no epic:${id}`)
    })
})
