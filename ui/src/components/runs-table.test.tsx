import { QueryClient } from '@tanstack/react-query'
import { cleanup, fireEvent, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { mockChores, mockReviews, mockRuns } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { ChoreSummary, ReviewSummary, Run } from '@/api/types'
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
        expect(row.getByRole('link', { name: 'review:5' }).getAttribute('href')).toBe('/reviews/5')
        expect(row.getByRole('link', { name: 'ABC-103' })).toBeDefined()
        expect(row.getByRole('link', { name: 'acme/web#91' })).toBeDefined()
        expect(row.getByText('review')).toBeDefined()
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

        fireEvent.click(screen.getByRole('button', { name: 'Show 1 earlier run' }))
        const earlier = within(screen.getByTestId('earlier-chore-runs-deps'))
        expect(earlier.getByRole('link', { name: '#2' })).toBeDefined()
        expect(earlier.getByText("One advisory touches web's lockfile.")).toBeDefined()
    })
})
