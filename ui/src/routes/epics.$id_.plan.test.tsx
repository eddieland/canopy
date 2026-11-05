import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import type { AnyRouter } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import type { Middleware } from 'openapi-fetch'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { mockEpicDetails, mockEpicPlans } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { EpicPlans } from '@/api/types'

import { Route } from './epics.$id_.plan'

// Half an hour after the mock journal's T0, as the screenshots are taken.
const NOW = new Date('2026-10-08T12:30:00Z')

// The server stand-in: every epic the mocks hold is read already, so what reaches it asks for one canopy has not.
const server: Middleware = {
    onRequest() {
        return Response.json({ detail: 'no such epic' }, { status: 404 })
    },
}

beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(NOW)
    api.use(server)
})

afterEach(() => {
    api.eject(server)
    cleanup()
    vi.useRealTimers()
})

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
async function renderPage(id: string, plans: EpicPlans[] = mockEpicPlans): Promise<void> {
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
    client.setQueryData(keys.attention, [])
    client.setQueryData(keys.tick, { tick: null, acknowledged: null })
    client.setQueryData(keys.meta, {})
    for (const detail of mockEpicDetails) {
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
        expect(description()).toBe(
            'Written by epic:2#3. It waits on you: canopy plan epic:2 --approve ' +
                'approves it, and canopy reply epic:2 asks for changes.',
        )
        const changes = screen.getByRole('button', { name: 'Changes since plan 2' })
        expect(changes.getAttribute('aria-pressed')).toBe('true')
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
