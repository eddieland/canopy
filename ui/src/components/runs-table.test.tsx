import { QueryClient } from '@tanstack/react-query'
import { cleanup, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockChores, mockReviews, mockRuns, mockTasks } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { ChoreSummary, ReviewSummary, Run, TaskSummary } from '@/api/types'
import { subjectRuns } from '@/lib/run-state'
import { renderRouted, tipOf } from '@/test-utils'

import { RunsTable, SubjectRunsTable } from './runs-table'

afterEach(() => {
    cleanup()
})

const [RUNNING, BLOCKED] = mockRuns as [Run, Run]

const PR_A = 'https://github.com/acme/web/pull/88'
const PR_B = 'https://github.com/acme/api/pull/12'

// A client that reads nothing: the tracker's links are unset.
function client(): QueryClient {
    const queries = new QueryClient()
    queries.setQueryDefaults(keys.meta, { enabled: false })
    return queries
}

function renderRuns(runs: Run[], props: { ticket?: boolean; ownPr?: string } = {}) {
    return renderRouted(<RunsTable runs={runs} {...props} />, { client: client() })
}

function run(fields: Partial<Run>): Run {
    return { ...BLOCKED, ...fields }
}

// A run one model served whole.
function servedBy(id: number, model: string): Run {
    return run({ id, models: { status: 'found', models: [{ model, replies: 3, cost_usd: 0.1 }], error: null } })
}

describe('RunsTable', () => {
    it('names each run’s ticket and opens its page, and the run’s own', async () => {
        await renderRuns([RUNNING])
        expect(screen.getByRole('link', { name: 'ABC-101' }).getAttribute('href')).toBe('/tickets/ABC-101')
        expect(screen.getByRole('link', { name: 'run:41' }).getAttribute('href')).toBe('/runs/41')
        expect(screen.getByText('Sign in with SSO')).toBeDefined()
    })

    it('leaves out the ticket on the ticket’s own page', async () => {
        await renderRuns([RUNNING], { ticket: false })
        expect(screen.queryByRole('link', { name: 'ABC-101' })).toBeNull()
        expect(screen.queryByText('Sign in with SSO')).toBeNull()
        expect(screen.getByRole('link', { name: 'run:41' })).toBeDefined()
    })

    it('says a running run’s latest tool call, and a status in words with the CLI’s spelling in its tip', async () => {
        await renderRuns([RUNNING, run({ id: 43, status: 'worker_failed', state: 'failed', activity: null })])
        const running = within(screen.getByTestId('run-41'))
        expect(running.getByText('bash')).toBeDefined()
        expect(running.getByText('npm test -- login')).toBeDefined()
        const failed = within(screen.getByTestId('run-43'))
        expect(tipOf(failed.getByText('worker failed'))).toBe('worker_failed')
        expect(failed.queryByTestId('run-doing')).toBeNull()
    })

    it('names the PRs a run pushed to, but the one whose page it is', async () => {
        await renderRuns([run({ prs: [PR_A, PR_B] })], { ownPr: PR_A })
        expect(screen.queryByRole('link', { name: 'acme/web#88' })).toBeNull()
        expect(screen.getByRole('link', { name: 'acme/api#12' })).toBeDefined()
    })

    it('names up to four worktrees, and counts the rest past three, every one in a tip', async () => {
        const four = ['w/1', 'w/2', 'w/3', 'w/4']
        const { unmount } = await renderRuns([run({ worktrees: four })])
        for (const path of four) {
            expect(screen.getByText(path)).toBeDefined()
        }
        expect(screen.queryByTestId('run-worktrees-more')).toBeNull()
        unmount()

        await renderRuns([run({ worktrees: [...four, 'w/5'] })])
        expect(screen.getByText('w/3')).toBeDefined()
        expect(screen.queryByText('w/4')).toBeNull()
        const more = screen.getByText('+2 more worktrees')
        expect(tipOf(more)).toBe('the worktrees it holds:\nw/1\nw/2\nw/3\nw/4\nw/5')
    })

    it('names each run’s model without its provider, +1 for a switch, each whole in its tip', async () => {
        const OPUS = { model: 'anthropic/claude-opus-4-1', replies: 23, cost_usd: 1.65 }
        const SONNET = { model: 'anthropic/claude-sonnet-4-5', replies: 1, cost_usd: 0.66 }
        const split = run({ id: 43, models: { status: 'found', models: [OPUS, SONNET], error: null } })
        await renderRuns([BLOCKED, split], { ticket: false })
        const one = within(screen.getByTestId('run-42')).getByTestId('run-model')
        expect(one.textContent).toBe('model claude-sonnet-4-5')
        expect(one.className).toContain('text-muted-foreground')
        const two = within(screen.getByTestId('run-43')).getByTestId('run-model')
        expect(two.textContent).toBe('model claude-opus-4-1 +1')
        expect(tipOf(two)).toBe(
            'anthropic/claude-opus-4-1 $1.65, 23 replies\nanthropic/claude-sonnet-4-5 $0.66, 1 reply',
        )
    })

    it('keeps the provider of a model another provider names alike', async () => {
        await renderRuns([servedBy(43, 'openai/gpt-5'), servedBy(44, 'azure/gpt-5'), BLOCKED])
        const named = screen.getAllByTestId('run-model').map((model) => model.textContent)
        expect(named).toEqual(['model openai/gpt-5', 'model azure/gpt-5', 'model claude-sonnet-4-5'])
    })

    it('names the model canopy asked for until the session is read, else unread, and why in its tip', async () => {
        await renderRuns([RUNNING, run({ id: 43, model: 'anthropic/claude-opus-4-1', models: RUNNING.models })])
        const unread = within(screen.getByTestId('run-41')).getByTestId('run-model')
        expect(unread.textContent).toBe('model unread')
        expect(tipOf(unread)).toBe('none: read from its session once it ends')
        const asked = within(screen.getByTestId('run-43')).getByTestId('run-model')
        expect(asked.textContent).toBe('asked claude-opus-4-1')
        expect(tipOf(asked)).toBe('asked anthropic/claude-opus-4-1, none served: read from its session once it ends')
    })

    it.each([
        ['unread', null, "none: not read yet: a tick reads a few ended runs' sessions"],
        ['failed', 'timed out', 'none: its session could not be read, tried again later (timed out)'],
    ] as const)('says a run whose session is %s is unread, why in its tip', async (status, error, why) => {
        await renderRuns([run({ models: { status, models: [], error } })])
        const model = screen.getByTestId('run-model')
        expect(model.textContent).toBe('model unread')
        expect(tipOf(model)).toBe(why)
    })

    it('names no model for a run with no session to read, which canopy asked none for', async () => {
        await renderRuns([run({ models: { status: 'no_session', models: [], error: null } })])
        expect(screen.queryByTestId('run-model')).toBeNull()
    })

    it('says what canopy asked for, then what served, when it served none of the replies', async () => {
        await renderRuns([run({ model: 'anthropic/claude-opus-4-1' })])
        const model = screen.getByTestId('run-model')
        expect(model.textContent).toBe('asked claude-opus-4-1 ≠ claude-sonnet-4-5')
        // Worth knowing, not waiting on the operator: the model that served in the foreground, no status color.
        expect(within(model).getByText('claude-sonnet-4-5').className).toContain('text-foreground')
        expect(model.outerHTML).not.toContain('text-status-')
    })

    it('raises nothing for a model at its default variant, which its session names alone', async () => {
        await renderRuns([run({ model: 'anthropic/claude-sonnet-4-5@high' })])
        const model = screen.getByTestId('run-model')
        expect(model.textContent).toBe('model claude-sonnet-4-5')
        expect(model.outerHTML).not.toContain('text-foreground')
    })

    it('leads with the model asked for when it served, and marks only the others', async () => {
        const HAIKU = { model: 'anthropic/claude-haiku-4-5', replies: 2, cost_usd: 0.9 }
        const OPUS = { model: 'anthropic/claude-opus-4-1', replies: 23, cost_usd: 0.4 }
        await renderRuns([
            run({
                model: 'anthropic/claude-opus-4-1',
                models: { status: 'found', models: [HAIKU, OPUS], error: null },
            }),
        ])
        const model = screen.getByTestId('run-model')
        expect(model.textContent).toBe('model claude-opus-4-1 +1')
        expect(within(model).getByText('+1', { exact: false }).className).toContain('text-foreground')
        expect(tipOf(model)).toBe(
            'anthropic/claude-haiku-4-5 $0.90, 2 replies\nanthropic/claude-opus-4-1 $0.40, 23 replies\n' +
                'asked anthropic/claude-opus-4-1',
        )
    })

    it('names no model where its page sends none and canopy asked for none', async () => {
        await renderRuns([run({ models: null })])
        expect(screen.queryByTestId('run-model')).toBeNull()
    })
})

describe('SubjectRunsTable', () => {
    // ABC-102 asked, was answered, and asked again; ABC-101 runs for the first time.
    const runs = [
        RUNNING,
        run({ id: 50, summary: 'Asked again about the color.' }),
        run({ id: 46, summary: 'Asked about the color.\nThe rest of what it said.' }),
        run({ id: 42, summary: null }),
    ]

    it('shows a ticket’s latest run, its earlier runs folded under it until opened', async () => {
        await renderRouted(<SubjectRunsTable groups={subjectRuns({ runs })} />, { client: client() })
        expect(screen.getByText('Asked again about the color.')).toBeDefined()
        expect(screen.queryByRole('link', { name: 'run:46' })).toBeNull()

        const show = screen.getByRole('button', { name: 'Show 2 earlier runs' })
        expect(show.getAttribute('aria-expanded')).toBe('false')
        fireEvent.click(show)
        const hide = screen.getByRole('button', { name: 'Hide 2 earlier runs' })
        expect(hide.getAttribute('aria-expanded')).toBe('true')
        const earlier = within(screen.getByTestId('earlier-runs-ABC-102'))
        expect(earlier.getAllByRole('link').map((link) => link.textContent)).toEqual(['run:46', 'run:42'])
        // An earlier run says the first line of what it said; its page has the rest.
        expect(earlier.getByText('Asked about the color.')).toBeDefined()
        expect(screen.queryByText(/The rest of what it said/u)).toBeNull()
        // Each names its model too, so the runs of a ticket with a model override read down by model.
        expect(earlier.getAllByTestId('run-model').map((model) => model.textContent)).toEqual([
            'model claude-sonnet-4-5',
            'model claude-sonnet-4-5',
        ])

        fireEvent.click(hide)
        expect(screen.queryByRole('link', { name: 'run:46' })).toBeNull()
    })

    it('has no fold for a ticket with one run, and says one earlier run in the singular', async () => {
        await renderRouted(<SubjectRunsTable groups={subjectRuns({ runs: runs.slice(0, 3) })} />, { client: client() })
        expect(screen.getAllByRole('button', { name: /earlier/u }).map((button) => button.textContent)).toEqual([
            'Show 1 earlier run',
        ])
    })

    it('lists a review by its PR, its ticket, and what it found, its earlier reviews folded under it', async () => {
        const [running] = mockReviews as [ReviewSummary]
        const done = { ...running, status: 'done', state: 'done' as const, ended_at: '2026-10-08T12:20:00Z' }
        const reviews = [
            { ...done, verdict: 'findings' as const, findings: 2 },
            { ...done, id: 3, ticket_key: null, verdict: 'clean' as const },
        ]
        const groups = subjectRuns({ runs: [], reviews })
        await renderRouted(<SubjectRunsTable groups={groups} />, { client: client() })
        const row = within(screen.getByTestId('review-5'))
        expect(row.getByRole('link', { name: 'review:5' }).getAttribute('href')).toBe('/pull-requests/reviews/5')
        expect(row.getByRole('link', { name: 'ABC-103' })).toBeDefined()
        expect(row.getByRole('link', { name: 'acme/web#91' })).toBeDefined()
        expect(row.getByText('review')).toBeDefined()
        // Titled as a worker's row is: by its PR's title, its own or else its ticket's.
        expect(row.getByText('ABC-103: move billing to v2 and drop the v1 client')).toBeDefined()
        expect(row.getByText('at 9b1d4e7')).toBeDefined()
        expect(row.getByText('2 findings')).toBeDefined()

        fireEvent.click(screen.getByRole('button', { name: 'Show 1 earlier run' }))
        const earlier = within(screen.getByTestId('earlier-reviews-5'))
        expect(earlier.getByRole('link', { name: 'review:3' })).toBeDefined()
        expect(earlier.getByText('clean')).toBeDefined()
    })

    it('lists a chore run by its number and its chore, its latest that ended under the one running', async () => {
        const [deps] = mockChores as [ChoreSummary]
        const running = { ...(deps.latest as NonNullable<ChoreSummary['latest']>), id: 3, status: 'running' }
        const chores = [{ ...deps, running: { ...running, state: 'running' as const, ended_at: null, summary: null } }]
        await renderRouted(<SubjectRunsTable groups={subjectRuns({ runs: [], chores })} />, { client: client() })
        const row = within(screen.getByTestId('chore-run-deps-3'))
        const number = row.getByRole('link', { name: '#3' })
        expect(number.getAttribute('href')).toBe('/chores/deps/runs/3')
        // The number and its chore read as its reference, which its hover gives whole.
        expect(number.getAttribute('title')).toBe('chore:deps#3')
        expect(row.getByRole('link', { name: 'chore:deps' }).getAttribute('href')).toBe('/chores/deps')
        expect(row.getByText('chore')).toBeDefined()
        expect(row.getByText('Dependency advisories')).toBeDefined()

        fireEvent.click(screen.getByRole('button', { name: 'Show 1 earlier run' }))
        const earlier = within(screen.getByTestId('earlier-chore-runs-deps'))
        expect(earlier.getByRole('link', { name: '#2' })).toBeDefined()
        expect(earlier.getByText("One advisory touches web's lockfile.")).toBeDefined()
    })

    it('lists a task by its newest run, as task:N#M opening its page, its repository, and its text', async () => {
        const [, running, waiting] = mockTasks as [unknown, TaskSummary, TaskSummary]
        const groups = subjectRuns({ runs: [], tasks: [running, waiting] })
        await renderRouted(<SubjectRunsTable groups={groups} />, { client: client() })
        const row = within(screen.getByTestId('task-run-6-8'))
        expect(row.getByRole('link', { name: 'task:6#8' }).getAttribute('href')).toBe('/tasks/6/runs/8')
        expect(row.getByText('running')).toBeDefined()
        expect(row.getByText('mobile')).toBeDefined()
        expect(row.getByText('task')).toBeDefined()
        expect(row.getByText("Add a dark launch screen to match the app's theme.")).toBeDefined()
        // Its runs before this one are on the task's page, not folded under it.
        expect(row.queryByRole('button', { name: /earlier/u })).toBeNull()

        const asked = within(screen.getByTestId('task-run-4-5'))
        expect(asked.getByText('blocked')).toBeDefined()
        expect(
            asked.getByText('The flag is also read by the billing worker in api; rename it there too?'),
        ).toBeDefined()
    })

    it('says untitled for a review or a chore with no title, so its title cell is never blank', async () => {
        const [review] = mockReviews as [ReviewSummary]
        const [deps] = mockChores as [ChoreSummary]
        const groups = subjectRuns({
            runs: [],
            reviews: [{ ...review, title: null }],
            chores: [{ ...deps, title: null }],
        })
        await renderRouted(<SubjectRunsTable groups={groups} />, { client: client() })
        expect(within(screen.getByTestId('review-5')).getByText('untitled')).toBeDefined()
        expect(within(screen.getByTestId('chore-run-deps-2')).getByText('untitled')).toBeDefined()
    })
})
