import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import type { AnyRouter } from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { keys } from '@/api/queries'
import type { SkillsAgent, SkillsReport, SkillsSkill, SkillsUse } from '@/api/types'

import { Route } from './reports.skills'

afterEach(() => {
    cleanup()
})

function used(by: string, counts: Partial<SkillsUse> = {}): SkillsUse {
    return {
        agent: by,
        offered: 4,
        loaded: 0,
        unoffered: 0,
        loads: 0,
        failed: 0,
        est_body_tokens: 0,
        front_matter_chars: 105,
        est_call_tokens: 26,
        counted: 2,
        calls: 128,
        est_front_matter_tokens: 3_360,
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
        est_body_tokens: 4_875,
        front_matter_chars: 105,
        est_call_tokens: 26,
        counted: 5,
        calls: 153,
        est_front_matter_tokens: 4_016,
        uses: [],
        ...counts,
    }
}

function agent(name: string, counts: Partial<SkillsAgent> = {}): SkillsAgent {
    return {
        agent: name,
        runs: 4,
        unanswered: 0,
        unasked: 0,
        listed: 4,
        unsized: 0,
        unread: 2,
        counted: 2,
        calls: 128,
        skills: 3,
        unused: 1,
        loads: 5,
        unnamed: 0,
        est_call_tokens: 387,
        est_front_matter_tokens: 49_600,
        ...counts,
    }
}

// A week of three skills over a worker and a reviewer: the tracker's, which most runs load, one that costs the most
// and one run loaded, and one nothing loaded; then a call that asked for a skill no run was offered. The tasks' runs,
// the private worker's, have no offer on record, and loaded the tracker's skill all the same.
const REPORT: SkillsReport = {
    days: 7,
    since: '2026-10-02T00:00:00Z',
    until: '2026-10-09T00:00:00Z',
    offered: 3,
    unused: 1,
    loads: 10,
    unnamed: 1,
    runs: 15,
    unanswered: 1,
    unasked: 3,
    listed: 9,
    unsized: 0,
    unread: 4,
    counted: 5,
    est_front_matter_tokens: 56_075,
    est_call_tokens: 366,
    skills: [
        skill('canopy', {
            offered: 0,
            loaded: 0,
            loads: 0,
            failed: 1,
            est_body_tokens: 0,
            front_matter_chars: null,
            est_call_tokens: null,
            counted: 0,
            calls: 0,
            est_front_matter_tokens: null,
            uses: [
                used('canopy-worker', {
                    offered: 0,
                    failed: 1,
                    front_matter_chars: null,
                    est_call_tokens: null,
                    counted: 0,
                    calls: 0,
                    est_front_matter_tokens: null,
                }),
            ],
        }),
        skill('design-system', {
            offered: 7,
            loaded: 1,
            loads: 1,
            est_body_tokens: 2_350,
            front_matter_chars: 926,
            est_call_tokens: 231,
            est_front_matter_tokens: 35_420,
            uses: [
                used('canopy-worker', {
                    loaded: 1,
                    loads: 1,
                    est_body_tokens: 2_350,
                    front_matter_chars: 926,
                    est_call_tokens: 231,
                    est_front_matter_tokens: 29_632,
                }),
                used('canopy-reviewer', {
                    offered: 3,
                    front_matter_chars: 926,
                    est_call_tokens: 231,
                    counted: 3,
                    calls: 25,
                    est_front_matter_tokens: 5_787,
                }),
            ],
        }),
        skill('terse', {
            unused: true,
            loaded: 0,
            loads: 0,
            est_body_tokens: 0,
            front_matter_chars: 5,
            est_call_tokens: 1,
            est_front_matter_tokens: 191,
            uses: [
                used('canopy-worker', { front_matter_chars: 5, est_call_tokens: 1, est_front_matter_tokens: 160 }),
                used('canopy-reviewer', {
                    offered: 5,
                    front_matter_chars: 5,
                    est_call_tokens: 1,
                    counted: 3,
                    calls: 25,
                    est_front_matter_tokens: 31,
                }),
            ],
        }),
        skill('tracker-jira', {
            unoffered: 3,
            loads: 9,
            failed: 1,
            uses: [
                used('canopy-worker', { loaded: 4, loads: 4, est_body_tokens: 3_250 }),
                used('canopy-reviewer', {
                    offered: 5,
                    loaded: 2,
                    loads: 2,
                    failed: 1,
                    est_body_tokens: 1_625,
                    counted: 3,
                    calls: 25,
                    est_front_matter_tokens: 656,
                }),
                used('canopy-worker-private', {
                    offered: 0,
                    unoffered: 3,
                    loads: 3,
                    est_body_tokens: 2_437,
                    front_matter_chars: null,
                    est_call_tokens: null,
                    counted: 0,
                    calls: 0,
                    est_front_matter_tokens: null,
                }),
            ],
        }),
    ],
    agents: [
        agent('canopy-overseer', {
            runs: 2,
            listed: 0,
            unread: 0,
            counted: 0,
            calls: 0,
            skills: 0,
            unused: 0,
            loads: 0,
            est_call_tokens: 0,
            est_front_matter_tokens: 0,
        }),
        agent('canopy-worker'),
        agent('canopy-worker-private', {
            runs: 3,
            unasked: 3,
            listed: 0,
            unread: 0,
            counted: 0,
            calls: 0,
            skills: null,
            unused: null,
            loads: 3,
            unnamed: 1,
            est_call_tokens: null,
            est_front_matter_tokens: null,
        }),
        agent('canopy-reviewer', {
            runs: 6,
            unanswered: 1,
            listed: 5,
            counted: 3,
            calls: 25,
            unused: 2,
            loads: 2,
            est_call_tokens: 259,
            est_front_matter_tokens: 6_475,
        }),
    ],
    previous: {
        since: '2026-09-25T00:00:00Z',
        until: '2026-10-02T00:00:00Z',
        offered: 3,
        unused: 0,
        est_call_tokens: 380,
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
function cells(table: string, rows: RegExp): (string | null)[][] {
    return within(screen.getByTestId(table))
        .getAllByTestId(rows)
        .map((row) => [...row.children].map((cell) => cell.textContent))
}

/** The bars an agent's row draws. */
function bars(name: string): HTMLElement[] {
    return within(screen.getByTestId(`skills-agent-${name}`)).queryAllByTestId('cell-bar')
}

/** What a table lists, in its order: its rows' heads. */
function names(table: string): (string | null)[] {
    return within(screen.getByTestId(table))
        .getAllByRole('rowheader')
        .map((head) => head.textContent)
}

describe('the Skills report', () => {
    it("says the window's state under its title, the cost with the runs it is counted in", async () => {
        await renderPage(REPORT)
        expect(
            await screen.findByText(
                '3 skills offered over 7 days · 1 never loaded · ' +
                    'front matter ~56.1k tokens in 5 of 9 runs offered a skill',
            ),
        ).toBeTruthy()
    })

    it("heads the page with the window's figures, none colored, a cost compared only by its mean a call", async () => {
        await renderPage(REPORT)
        const tiles = await screen.findByTestId('skills-tiles')
        expect(
            within(tiles)
                .getAllByRole('term')
                .map((t) => t.textContent),
        ).toEqual(['skills offered', 'never loaded', '~tokens a call', 'front matter ~tokens'])
        const shown = ['offered', 'unused', 'call', 'sent']
        expect(shown.map((key) => within(tiles).getByTestId(`skills-${key}`).textContent)).toEqual([
            '3',
            '1',
            '366',
            '56.1k',
        ])
        expect(shown.slice(0, 3).map((key) => within(tiles).getByTestId(`skills-${key}-delta`).textContent)).toEqual([
            'same as the 7 days before',
            '+1 on the 7 days before',
            '−14 on the 7 days before',
        ])
        // A skill never loaded is a cost, not a thing broken: no move is red. The sum has no delta at all, since it
        // grows with the runs counted.
        for (const key of shown.slice(0, 3)) {
            expect(within(tiles).getByTestId(`skills-${key}-delta`).className).not.toContain('text-status-failed')
        }
        expect(within(tiles).queryByTestId('skills-sent-delta')).toBeNull()
        expect(within(screen.getByRole('banner')).getByRole('radiogroup', { name: 'Window' })).toBeTruthy()
    })

    it('lists the agents by the heaviest list a call, a known nothing apart from what is not known', async () => {
        await renderPage(REPORT)
        await screen.findByTestId('skills-agent-table')
        expect(cells('skills-agent-table', /^skills-agent-/u)).toEqual([
            ['canopy-worker', '4', '0', '3', '1', '387', '', '49.6k', '5'],
            ['canopy-reviewer', '6', '1', '3', '2', '259', '', '6.5k', '2'],
            // Offered no skill, which the runtime said: zeros, and an empty bar.
            ['canopy-overseer', '2', '0', '0', '0', '0', '', '0', '0'],
            // No offer on record for any run: nothing says what it was offered, so dashes, and no bar. Its loads
            // are counted all the same.
            ['canopy-worker-private', '3', '3', '–', '–', '–', '', '–', '3'],
        ])
        expect(bars('canopy-overseer')).toHaveLength(1)
        expect(bars('canopy-worker-private')).toHaveLength(0)
        expect(screen.getByTestId('skills-offers').textContent).toBe(
            'No offer on record for 4 of 15 runs: the runtime could not answer for 1, and canopy never asked about ' +
                "3, a task's, an epic's plan, or one from before it asked. They count under the agent canopy ships " +
                'for their kind of run, and their loads are counted.',
        )
    })

    it('lists each skill over every agent by the front matter it came to, never for one no run loaded', async () => {
        await renderPage(REPORT)
        await screen.findByTestId('skills-skill-table')
        expect(cells('skills-skill-table', /^skills-skill-/u)).toEqual([
            ['design-system', '7', '14%', '231', '35.4k', '', '1', '0', '2.4k'],
            ['tracker-jira', '9', '67%', '26', '4.0k', '', '9', '1', '4.9k'],
            ['terse', '9', 'never', '1', '191', '', '0', '0', '0'],
            // Asked for by a call that failed, and offered to no run: nothing to rate, size, or cost.
            ['canopy', '–', '–', '–', '–', '', '0', '1', '0'],
        ])
        expect(screen.getByTestId('skills-scope').textContent).toBe('every agent')
        expect(screen.getByTestId('skills-count').textContent).toBe('4')
        expect(screen.getByTestId('skills-coverage').textContent).toBe(
            'Front matter is counted over 5 of the 9 runs offered a skill: 4 with no session read yet. 1 load named ' +
                'no skill canopy could read: any skill here may be the one it loaded.',
        )
    })

    it('narrows the skills to an agent picked by its name, the columns unchanged, and widens them again', async () => {
        const router = await renderPage(REPORT)
        const agents = await screen.findByTestId('skills-agent-table')
        fireEvent.click(within(agents).getByRole('link', { name: 'canopy-reviewer' }))
        await waitFor(() => {
            expect(router.state.location.search).toEqual({ agent: 'canopy-reviewer' })
        })
        expect(screen.getByTestId('skills-scope').textContent).toBe('canopy-reviewer')
        expect(screen.getByTestId('skills-count').textContent).toBe('3 of 4')
        // Its own runs alone: the skill a worker loaded and it never did reads never for it.
        expect(cells('skills-skill-table', /^skills-skill-/u)).toEqual([
            ['design-system', '3', 'never', '231', '5.8k', '', '0', '0', '0'],
            ['tracker-jira', '5', '40%', '26', '656', '', '2', '1', '1.6k'],
            ['terse', '5', 'never', '1', '31', '', '0', '0', '0'],
        ])
        // The picked agent's row is the page's own: marked, as the page shown is.
        expect(within(agents).getByRole('link', { name: 'canopy-reviewer' }).getAttribute('aria-current')).toBe('page')
        fireEvent.click(within(screen.getByTestId('skills-skills')).getByRole('link', { name: 'every agent' }))
        await waitFor(() => {
            expect(router.state.location.search).toEqual({})
        })
        expect(screen.getByTestId('skills-count').textContent).toBe('4')
    })

    it('shows an agent with no offer on record by its loads alone, and one offered nothing as none', async () => {
        await renderPage(REPORT, '/reports/skills?agent=canopy-worker-private')
        await screen.findByTestId('skills-skill-table')
        // Loaded in three runs nothing says what they were offered: no rate, no size, no cost.
        expect(cells('skills-skill-table', /^skills-skill-/u)).toEqual([
            ['tracker-jira', '–', '–', '–', '–', '', '3', '0', '2.4k'],
        ])
        cleanup()
        await renderPage(REPORT, '/reports/skills?agent=canopy-overseer')
        expect(await screen.findByTestId('skills-scope')).toBeTruthy()
        expect(screen.getByTestId('skills-skills').textContent).toContain(
            'no skill was offered to canopy-overseer or loaded by it in these 7 days',
        )
        expect(screen.getByTestId('skills-count').textContent).toBe('0 of 4')
    })

    it('reads an agent the window does not have as every agent', async () => {
        await renderPage(REPORT, '/reports/skills?agent=canopy-planner')
        await screen.findByTestId('skills-skill-table')
        expect(screen.getByTestId('skills-scope').textContent).toBe('every agent')
        expect(names('skills-skill-table')).toHaveLength(4)
    })

    it('orders the skills by how often each is loaded from the header, kept in the search', async () => {
        const router = await renderPage(REPORT)
        const sort = await screen.findByRole('radiogroup', { name: 'Sort' })
        expect(within(sort).getByRole('radio', { name: 'front matter' }).dataset['state']).toBe('on')
        fireEvent.click(within(sort).getByRole('radio', { name: 'least loaded' }))
        await waitFor(() => {
            expect(router.state.location.search).toEqual({ order: 'least' })
        })
        // The skill no run loaded first, then the lowest rates; one with no rate last.
        expect(names('skills-skill-table')).toEqual(['terse', 'design-system', 'tracker-jira', 'canopy'])
        fireEvent.click(within(sort).getByRole('radio', { name: 'most loaded' }))
        await waitFor(() => {
            expect(router.state.location.search).toEqual({ order: 'most' })
        })
        expect(names('skills-skill-table')).toEqual(['tracker-jira', 'design-system', 'terse', 'canopy'])
        fireEvent.click(within(sort).getByRole('radio', { name: 'front matter' }))
        await waitFor(() => {
            expect(router.state.location.search).toEqual({})
        })
    })

    it("says a skill named outside the runtime's rule has loads it cannot count, not that none loaded it", async () => {
        const odd = skill('My_Skill', {
            countable: false,
            loaded: 0,
            loads: 0,
            est_body_tokens: 0,
            uses: [used('canopy-worker')],
        })
        await renderPage({ ...REPORT, skills: [odd] })
        await screen.findByTestId('skills-skill-table')
        expect(cells('skills-skill-table', /^skills-skill-/u)).toEqual([
            ['My_Skill', '9', '–', '26', '4.0k', '', '–', '0', '–'],
        ])
    })

    it('leaves the cost out while no run is counted, rather than show it as nothing', async () => {
        const unsized = REPORT.skills.map((s) => ({
            ...s,
            front_matter_chars: null,
            est_call_tokens: null,
            counted: 0,
            calls: 0,
            est_front_matter_tokens: null,
        }))
        await renderPage({
            ...REPORT,
            unsized: 9,
            unread: 0,
            counted: 0,
            est_front_matter_tokens: null,
            est_call_tokens: null,
            skills: unsized,
        })
        expect(
            await screen.findByText('3 skills offered over 7 days · 1 never loaded · front matter not counted yet'),
        ).toBeTruthy()
        // No tile of a dash: the two of front matter are not there to read as nothing.
        const tiles = screen.getByTestId('skills-tiles')
        expect(
            within(tiles)
                .getAllByRole('term')
                .map((t) => t.textContent),
        ).toEqual(['skills offered', 'never loaded'])
        // Offered and loaded are still counted, and the skills most offered lead meanwhile.
        expect(cells('skills-skill-table', /^skills-skill-/u).map((row) => row.slice(0, 6))).toEqual([
            ['terse', '9', 'never', '–', '–', ''],
            ['tracker-jira', '9', '67%', '–', '–', ''],
            ['design-system', '7', '14%', '–', '–', ''],
            ['canopy', '–', '–', '–', '–', ''],
        ])
        expect(screen.getByTestId('skills-coverage').textContent).toContain(
            "Front matter is counted over 0 of the 9 runs offered a skill: 9 from before canopy kept a description's " +
                'length.',
        )
    })

    it('says so when no agent ran', async () => {
        await renderPage({
            ...REPORT,
            offered: 0,
            unused: 0,
            loads: 0,
            unnamed: 0,
            runs: 0,
            unanswered: 0,
            unasked: 0,
            listed: 0,
            unread: 0,
            counted: 0,
            est_front_matter_tokens: null,
            est_call_tokens: null,
            skills: [],
            agents: [],
        })
        expect(await screen.findByText('no skill offered over 7 days')).toBeTruthy()
        expect(screen.getByText('no agent ran in these 7 days')).toBeTruthy()
        expect(screen.getByText('no skill was offered or loaded in these 7 days')).toBeTruthy()
        expect(screen.getByTestId('skills-coverage').textContent).toBe(
            'No run was offered a skill on record, so no front matter is counted.',
        )
    })

    it('reads 30 days from the search, as the reports page links it', async () => {
        await renderPage({ ...REPORT, days: 30 }, '/reports/skills?days=30')
        expect(await screen.findByText(/^3 skills offered over 30 days · 1 never loaded · /u)).toBeTruthy()
        expect(screen.getByTestId('skills-window-30').dataset['state']).toBe('on')
        expect(screen.getByTestId('skills-unused-delta').textContent).toBe('+1 on the 30 days before')
    })
})
