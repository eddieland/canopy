// Typed fixtures for unit tests, a few of the rows canopy/serve/mock.py seeds its journal with. The dev server and the
// end-to-end tests get the whole seeded journal from `python -m canopy.serve --mock`.
import type { AttentionItem, Run, TicketSummary } from './types'

export const mockRuns: Run[] = [
    {
        id: 41,
        ticket_key: 'ABC-101',
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
        private: true,
        start: 'started',
        phase: 'needs_human',
        done: false,
        branch: 'agent/ABC-102-export',
        active_at: '2026-10-08T11:56:00Z',
        latest_message_id: 5,
        awaiting: 5,
        running_run: null,
    },
]
