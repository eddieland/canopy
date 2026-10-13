// Typed fixtures for unit tests, a few of the rows canopy/serve/mock.py seeds its journal with. The dev server and the
// end-to-end tests get the whole seeded journal from `python -m canopy.serve --mock`.
import type { AttentionItem, ChoreSummary, Run, SearchHit, TicketSummary } from './types'

export const mockRuns: Run[] = [
    {
        id: 41,
        ticket_key: 'ABC-101',
        ticket_title: 'Sign in with SSO',
        kind: 'implement',
        status: 'running',
        state: 'running',
        private: false,
        branch: 'agent/ABC-101-login',
        started_at: '2026-10-08T12:00:00Z',
        ended_at: null,
        summary: null,
        prs: [],
        session_id: 'ses_mock41',
        cost_usd: 0.42,
        tokens: 19320,
        worktrees: ['.treehouse/web-3f9c2a1b/1/web'],
        log_path: '/home/op/.canopy/runs/41.log',
    },
    {
        id: 42,
        ticket_key: 'ABC-102',
        ticket_title: 'Export reports as CSV',
        kind: 'implement',
        status: 'blocked',
        state: 'blocked',
        private: true,
        branch: 'agent/ABC-102-export',
        started_at: '2026-10-08T11:30:00Z',
        ended_at: '2026-10-08T11:56:00Z',
        summary: 'Added the export button and its CSV writer; its color waits on you.',
        prs: [],
        session_id: 'ses_mock42',
        cost_usd: 1.07,
        tokens: 49220,
        worktrees: [],
        log_path: '/home/op/.canopy/runs/42.log',
    },
]

export const mockAttention: AttentionItem[] = [
    {
        id: 'a1',
        subject: 'ABC-102',
        ticket_key: 'ABC-102',
        chore: null,
        repo: null,
        reason: 'awaiting_reply',
        detail: 'message 5: Should the export button be red or blue?',
        since: '2026-10-08T11:56:00Z',
        finding: false,
    },
]

export const mockTickets: TicketSummary[] = [
    {
        key: 'ABC-102',
        title: 'Export reports as CSV',
        private: true,
        start: 'started',
        phase: 'needs_human',
        last_decision: 'wait',
        done: false,
        branch: 'agent/ABC-102-export',
        active_at: '2026-10-08T11:56:00Z',
        latest_message_id: 5,
        awaiting: 5,
        running_run: null,
    },
]

export const mockChores: ChoreSummary[] = [
    {
        name: 'deps',
        every_minutes: 360,
        days: ['mon', 'tue', 'wed', 'thu', 'fri'],
        hours: '08:00-18:00',
        timezone: 'UTC',
        when: 'Skip it when nothing has merged to main since the last run.',
        running: null,
        latest: {
            id: 2,
            status: 'ok',
            state: 'done',
            started_at: '2026-10-08T08:00:00Z',
            ended_at: '2026-10-08T08:07:00Z',
            summary: "One advisory touches web's lockfile.",
            findings: 1,
            session_id: 'ses_chore2',
            cost_usd: 0.26,
            tokens: 11960,
            log_path: '/home/op/.canopy/chores/2.log',
        },
        due_at: '2026-10-08T14:00:00Z',
        findings: [
            {
                id: 'lodash-advisory',
                title: 'lodash 4.17.20 has a prototype pollution advisory',
                detail: "web's lockfile pins lodash 4.17.20 through an old date picker; 4.17.21 fixes it.",
                link: 'https://github.com/advisories/GHSA-35jh-r3h4-6jhm',
                since: '2026-10-08T08:00:00Z',
            },
        ],
        latest_note_id: 8,
    },
]

/** A search hit: a worker's report on ABC-099, with whatever `fields` replace. */
export function hit(fields: Partial<SearchHit> = {}): SearchHit {
    return {
        source: 'message',
        at: '2026-10-08T10:59:00Z',
        snippet: 'Search now debounces input and cancels stale requests.',
        ticket_key: 'ABC-099',
        chore: null,
        run_id: 39,
        tick_id: null,
        label: 'report',
        ...fields,
    }
}
