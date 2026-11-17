import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import type { AnyRouter } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { keys } from '@/api/queries'
import type { SkillsReport, SkillsSkill, SkillsUse } from '@/api/types'

import { Route } from './reports.skills'

afterEach(() => {
    cleanup()
})

function used(agent: string, counts: Partial<SkillsUse> = {}): SkillsUse {
    return {
        agent,
        offered: 4,
        loaded: 0,
        unoffered: 0,
        loads: 0,
        failed: 0,
        est_result_tokens: 0,
        front_matter_chars: 105,
        counted: 2,
        calls: 128,
        est_sent_tokens: 3_360,
        ...counts,
    }
}

function skill(name: string, counts: Partial<SkillsSkill> = {}): SkillsSkill {
    return {
        name,
        countable: true,
        unused: false,
        offered: 9,
        loaded: 6,
        unoffered: 0,
        loads: 6,
        failed: 0,
        est_result_tokens: 4_875,
        front_matter_chars: 105,
        est_front_matter_tokens: 26,
        counted: 5,
        calls: 153,
        est_sent_tokens: 4_016,
        uses: [],
        ...counts,
    }
}

// A week of three skills over a worker and a reviewer: the tracker's, which most runs load, one that costs the most
// and one run loaded, and one nothing loaded; then a call that asked for a skill no run was offered.
const REPORT: SkillsReport = {
    days: 7,
    since: '2026-10-02T00:00:00Z',
    until: '2026-10-09T00:00:00Z',
    offered: 3,
    unused: 1,
    loads: 9,
    unnamed: 1,
    runs: 14,
    said: 9,
    counted: 5,
    est_sent_tokens: 44_000,
    est_call_tokens: 287,
    skills: [
        skill('canopy', {
            offered: 0,
            loaded: 0,
            loads: 0,
            failed: 1,
            est_result_tokens: 0,
            front_matter_chars: null,
            est_front_matter_tokens: null,
            counted: 0,
            calls: 0,
            est_sent_tokens: 0,
            uses: [used('canopy-worker', { offered: 0, failed: 1, front_matter_chars: null, counted: 0, calls: 0 })],
        }),
        skill('design-system', {
            offered: 7,
            loaded: 1,
            loads: 1,
            est_result_tokens: 2_350,
            front_matter_chars: 926,
            est_front_matter_tokens: 231,
            counted: 5,
            calls: 153,
            est_sent_tokens: 35_420,
            uses: [
                used('canopy-worker', { loaded: 1, loads: 1, est_sent_tokens: 29_632 }),
                used('canopy-reviewer', { offered: 3, counted: 3, calls: 25, est_sent_tokens: 5_787 }),
            ],
        }),
        skill('terse', {
            unused: true,
            loaded: 0,
            loads: 0,
            est_result_tokens: 0,
            front_matter_chars: 5,
            est_front_matter_tokens: 1,
            est_sent_tokens: 191,
            uses: [used('canopy-worker'), used('canopy-reviewer', { offered: 5, counted: 3, calls: 25 })],
        }),
        skill('tracker-jira', {
            unoffered: 3,
            loads: 9,
            failed: 1,
            uses: [
                used('canopy-worker', { loaded: 4, loads: 4 }),
                used('canopy-reviewer', {
                    offered: 5,
                    loaded: 2,
                    loads: 2,
                    counted: 3,
                    calls: 25,
                    est_sent_tokens: 656,
                }),
                used('canopy-worker-private', { offered: 0, unoffered: 3, loads: 3, counted: 0, calls: 0 }),
            ],
        }),
    ],
    agents: [
        {
            agent: 'canopy-overseer',
            runs: 2,
            said: 2,
            unanswered: 0,
            unasked: 0,
            counted: 2,
            calls: 25,
            skills: 0,
            unused: 0,
            est_call_tokens: 0,
            est_sent_tokens: 0,
        },
        {
            agent: 'canopy-worker',
            runs: 4,
            said: 4,
            unanswered: 0,
            unasked: 0,
            counted: 2,
            calls: 128,
            skills: 3,
            unused: 1,
            est_call_tokens: 387,
            est_sent_tokens: 49_600,
        },
        {
            agent: 'canopy-worker-private',
            runs: 3,
            said: 0,
            unanswered: 0,
            unasked: 3,
            counted: 0,
            calls: 0,
            skills: 0,
            unused: 0,
            est_call_tokens: null,
            est_sent_tokens: 0,
        },
        {
            agent: 'canopy-reviewer',
            runs: 6,
            said: 5,
            unanswered: 1,
            unasked: 0,
            counted: 3,
            calls: 25,
            skills: 3,
            unused: 2,
            est_call_tokens: 259,
            est_sent_tokens: 6_475,
        },
    ],
    previous: {
        since: '2026-09-25T00:00:00Z',
        until: '2026-10-02T00:00:00Z',
        offered: 3,
        unused: 0,
        loads: 4,
        counted: 2,
        est_sent_tokens: 9_000,
        est_call_tokens: 300,
    },
}

/** The Skills report at `path`, its window's report already read as `report`; the router, to see where it goes. */
async function renderPage(report: SkillsReport, path = '/reports/skills') {
    // Nothing reads the server: the report is the one set here, and every other query stays off.
    const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
    client.setQueryData(keys.skillsReport(report.days), report)
    const root = createRootRoute()
    const page = Route.update({ id: '/reports/skills', path: '/reports/skills', getParentRoute: () => root } as never)
    const router = createRouter({
        routeTree: root.addChildren([page]),
        history: createMemoryHistory({ initialEntries: [path] }),
    })
    await router.load()
    render(
        <QueryClientProvider client={client}>
            <RouterProvider router={router as AnyRouter} />
        </QueryClientProvider>,
    )
    return router
}

/** A table's rows as their cells' text: a bar's cell sits beside its figure's, empty for a screen reader. */
function cells(table: HTMLElement, rows: RegExp): (string | null)[][] {
    return within(table)
        .getAllByTestId(rows)
        .map((row) => [...row.children].map((cell) => cell.textContent))
}

/** The bars a skill's row of By skill draws. */
function bars(name: string): HTMLElement[] {
    return within(screen.getByTestId(`skills-skill-${name}`)).queryAllByTestId('cell-bar')
}

/** The skills a table lists, in its order: its rows' heads. */
function names(table: string): (string | null)[] {
    return within(screen.getByTestId(table))
        .getAllByRole('rowheader')
        .map((head) => head.textContent)
}

describe('the Skills report', () => {
    it("says the window's state under its title", async () => {
        await renderPage(REPORT)
        expect(
            await screen.findByText('3 skills offered over 7 days · 1 never loaded · ~44.0k tokens of front matter'),
        ).toBeTruthy()
    })

    it("heads the page with the window's figures, a cost compared only by its mean a call", async () => {
        await renderPage(REPORT)
        const tiles = await screen.findByTestId('skills-tiles')
        expect(
            within(tiles)
                .getAllByRole('term')
                .map((t) => t.textContent),
        ).toEqual(['skills offered', 'never loaded', 'loads', '~tokens a call', 'front matter ~tokens'])
        const shown = ['offered', 'unused', 'loads', 'call', 'sent']
        expect(shown.map((key) => within(tiles).getByTestId(`skills-${key}`).textContent)).toEqual([
            '3',
            '1',
            '9',
            '287',
            '44.0k',
        ])
        expect(shown.slice(0, 4).map((key) => within(tiles).getByTestId(`skills-${key}-delta`).textContent)).toEqual([
            'same as the 7 days before',
            '+1 on the 7 days before',
            '+5 on the 7 days before',
            '−13 on the 7 days before',
        ])
        // More skills never loaded is a move for the worse; a cost is never colored, and the sum has no delta: it
        // grows with the runs counted.
        expect(within(tiles).getByTestId('skills-unused-delta').className).toContain('text-status-failed')
        expect(within(tiles).getByTestId('skills-call-delta').className).not.toContain('text-status-failed')
        expect(within(tiles).queryByTestId('skills-sent-delta')).toBeNull()
        expect(within(screen.getByRole('banner')).getByRole('radiogroup', { name: 'Window' })).toBeTruthy()
    })

    it('lists each skill by the front matter it sent, and says what a row means where it could mislead', async () => {
        await renderPage(REPORT)
        const table = await screen.findByTestId('skills-skill-table')
        expect(cells(table, /^skills-skill-/u)).toEqual([
            ['design-system', '7', '1', '14%', '', '231', '35.4k', '', '1', '2.4k', ''],
            ['tracker-jira', '9', '6', '67%', '', '26', '4.0k', '', '9', '4.9k', ''],
            ['terse', '9', '0', '0%', '', '1', '191', '', '0', '0', 'never loaded'],
            // Asked for by a call that failed, and offered to no run: nothing to rate, size, or cost.
            ['canopy', '0', '0', '–', '', '–', '–', '', '0', '0', 'not offered'],
        ])
        expect(screen.getByTestId('skills-count').textContent).toBe('4')
        expect(screen.getByTestId('skills-coverage').textContent).toBe(
            'Front matter is counted over 5 of the 9 runs the runtime answered for: a run whose offer is from before ' +
                "canopy kept a description's length, or whose session is not read yet, is left out. 1 load named no " +
                'skill canopy could read, and counts under none.',
        )
    })

    it('draws a bar for a share of something, and none where there is nothing to have a share of', async () => {
        await renderPage(REPORT)
        await screen.findByTestId('skills-skill-table')
        // Never loaded is an empty bar; never offered, and never counted, are no bar at all.
        expect(bars('terse')).toHaveLength(2)
        expect(bars('canopy')).toHaveLength(0)
    })

    it('orders the skills by another figure from the header, kept in the search', async () => {
        const router = await renderPage(REPORT)
        const sort = await screen.findByRole('radiogroup', { name: 'Sort' })
        expect(within(sort).getByRole('radio', { name: 'front matter' }).dataset['state']).toBe('on')
        fireEvent.click(within(sort).getByRole('radio', { name: 'load rate' }))
        await waitFor(() => {
            expect(router.state.location.search).toEqual({ order: 'rate' })
        })
        expect(names('skills-skill-table')).toEqual(['terse', 'design-system', 'tracker-jira', 'canopy'])
        // The grid under it keeps the order, so a row is the same skill in both.
        expect(names('skills-grid')).toEqual(names('skills-skill-table'))
        fireEvent.click(within(sort).getByRole('radio', { name: 'front matter' }))
        await waitFor(() => {
            expect(router.state.location.search).toEqual({})
        })
    })

    it('sets each skill against each agent: loaded of offered, a dash where it was not offered', async () => {
        await renderPage(REPORT)
        const grid = await screen.findByTestId('skills-grid')
        // An agent offered no skill, the overseer, heads no column.
        expect(
            within(grid)
                .getAllByRole('columnheader')
                .map((head) => head.textContent),
        ).toEqual(['skill', 'worker', 'worker-private', 'reviewer'])
        expect(cells(grid, /^skills-grid-/u)).toEqual([
            ['design-system', '1/4', '', '–', '', '0/3', ''],
            // Loaded by the tasks' runs, which no offer is on record for.
            ['tracker-jira', '4/4', '', '3 loaded', '', '2/5', ''],
            ['terse', '0/4', '', '–', '', '0/5', ''],
            ['canopy', '–', '', '–', '', '–', ''],
        ])
        const tracker = within(screen.getByTestId('skills-grid-tracker-jira')).getAllByTestId('cell-bar')
        expect(tracker.map((bar) => (bar.firstElementChild as HTMLElement | null)?.style.width)).toEqual([
            '100%',
            '40%',
        ])
        expect(screen.getByTestId('skills-grid-key').textContent).toContain(
            'an empty bar is a skill the agent was offered and never loaded, a dash one it was not offered',
        )
    })

    it("counts each agent's runs and what its list costs a call, and notes what that leaves out", async () => {
        await renderPage(REPORT)
        const table = await screen.findByTestId('skills-agent-table')
        expect(cells(table, /^skills-agent-/u)).toEqual([
            ['canopy-overseer', '2', '2', '0', '0', '0', '', '0', 'offered no skill'],
            ['canopy-worker', '4', '4', '3', '1', '387', '', '49.6k', 'cost counted over 2 of 4'],
            // Never asked about: nothing says what it was offered, which is not being offered nothing.
            ['canopy-worker-private', '3', '0', '–', '–', '–', '', '–', '3 never asked about'],
            ['canopy-reviewer', '6', '5', '3', '2', '259', '', '6.5k', '1 not answered for · cost counted over 3 of 5'],
        ])
        expect(screen.getByTestId('skills-unasked').textContent).toBe(
            "3 runs were never asked what they were offered: a task's, an epic's plan, or one from before canopy " +
                'asked. The runtime could not answer for 1 run. Their loads are counted all the same.',
        )
    })

    it("says a skill named outside the runtime's rule has loads it cannot count, not that none loaded it", async () => {
        const odd = skill('My_Skill', {
            countable: false,
            loaded: 0,
            loads: 0,
            est_result_tokens: 0,
            uses: [used('canopy-worker')],
        })
        await renderPage({ ...REPORT, skills: [odd] })
        const table = await screen.findByTestId('skills-skill-table')
        expect(cells(table, /^skills-skill-/u)).toEqual([
            ['My_Skill', '9', '–', '–', '', '26', '4.0k', '', '–', '–', 'loads not counted'],
        ])
        // Offered to the worker, which is all its cell can say; the reviewer was not offered it.
        expect(cells(screen.getByTestId('skills-grid'), /^skills-grid-/u)).toEqual([
            ['My_Skill', 'offered', '', '–', ''],
        ])
    })

    it('has no cost to show while no offer has recorded a length, and says what the figures wait on', async () => {
        const unsized = REPORT.skills.map((s) => ({
            ...s,
            front_matter_chars: null,
            est_front_matter_tokens: null,
            counted: 0,
            calls: 0,
            est_sent_tokens: 0,
        }))
        await renderPage({
            ...REPORT,
            counted: 0,
            est_sent_tokens: 0,
            est_call_tokens: null,
            skills: unsized,
            previous: { ...REPORT.previous, counted: 0, est_sent_tokens: 0, est_call_tokens: null },
        })
        expect(await screen.findByText('3 skills offered over 7 days · 1 never loaded')).toBeTruthy()
        const tiles = screen.getByTestId('skills-tiles')
        expect(within(tiles).getByTestId('skills-call').textContent).toBe('–')
        expect(within(tiles).getByTestId('skills-sent').textContent).toBe('–')
        expect(within(tiles).queryByTestId('skills-call-delta')).toBeNull()
        // Offered and loaded are still counted: only the cost waits, and the skills most offered lead meanwhile.
        expect(
            cells(screen.getByTestId('skills-skill-table'), /^skills-skill-/u).map((row) => row.slice(0, 8)),
        ).toEqual([
            ['terse', '9', '0', '0%', '', '–', '–', ''],
            ['tracker-jira', '9', '6', '67%', '', '–', '–', ''],
            ['design-system', '7', '1', '14%', '', '–', '–', ''],
            ['canopy', '0', '0', '–', '', '–', '–', ''],
        ])
        expect(screen.getByTestId('skills-coverage').textContent).toContain(
            'Front matter is counted over 0 of the 9 runs the runtime answered for',
        )
    })

    it('says so when no run was offered or loaded a skill', async () => {
        await renderPage({
            ...REPORT,
            offered: 0,
            unused: 0,
            loads: 0,
            unnamed: 0,
            runs: 0,
            said: 0,
            counted: 0,
            est_sent_tokens: 0,
            est_call_tokens: null,
            skills: [],
            agents: [],
        })
        expect(await screen.findByText('no skill offered over 7 days')).toBeTruthy()
        expect(screen.getAllByText('no skill offered or loaded in these 7 days')).toHaveLength(2)
        expect(screen.getByText('no agent ran in these 7 days')).toBeTruthy()
    })

    it('reads 30 days from the search, as the reports page links it', async () => {
        await renderPage({ ...REPORT, days: 30 }, '/reports/skills?days=30')
        expect(
            await screen.findByText('3 skills offered over 30 days · 1 never loaded · ~44.0k tokens of front matter'),
        ).toBeTruthy()
        expect(screen.getByTestId('skills-window-30').dataset['state']).toBe('on')
        expect(screen.getByTestId('skills-unused-delta').textContent).toBe('+1 on the 30 days before')
    })
})
