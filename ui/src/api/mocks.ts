// Typed fixtures for unit tests, a few of the rows canopy/serve/mock.py seeds its journal with. The dev server and the
// end-to-end tests get the whole seeded journal from `python -m canopy.serve --mock`.
import type {
    AttentionItem,
    Capacity,
    ChoreSummary,
    Draft,
    PullRequestThreads,
    ReviewDraft,
    ReviewSummary,
    ReviewThread,
    Run,
    SearchHit,
    TicketSummary,
} from './types'

/** The default `[capacity]`: two workers, one review among them, and one chore apart. */
export const mockCapacity: Capacity = { workers: 2, reviews: 1, chores: 1 }

/** Two runs: one running, one blocked on a question. */
export const mockRuns: Run[] = [
    {
        id: 41,
        ticket_key: 'ABC-101',
        ticket_title: 'Sign in with SSO',
        kind: 'implement',
        reasons: [],
        status: 'running',
        state: 'running',
        private: false,
        ticket_stopped: false,
        branch: 'agent/ABC-101-login',
        started_at: '2026-10-08T12:00:00Z',
        ended_at: null,
        summary: null,
        prs: [],
        session_id: 'ses_mock41',
        cost_usd: 0.42,
        new_tokens: 19320,
        peak_context: 25200,
        worktrees: ['.treehouse/web-3f9c2a1b/1/web'],
        log_path: '/home/op/.canopy/runs/41.log',
        activity: { tool: 'bash', did: 'npm test -- login', at: '2026-10-08T12:27:00Z' },
        persona: 'canopy',
        persona_digest: '6c1f0a3e9b2d4c5a7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d',
        models: { status: 'running', models: [], error: null },
    },
    {
        id: 42,
        ticket_key: 'ABC-102',
        ticket_title: 'Export reports as CSV',
        kind: 'implement',
        reasons: [],
        status: 'blocked',
        state: 'blocked',
        private: true,
        ticket_stopped: false,
        branch: 'agent/ABC-102-export',
        started_at: '2026-10-08T11:30:00Z',
        ended_at: '2026-10-08T11:56:00Z',
        summary: 'Added the export button and its CSV writer; its color waits on you.',
        prs: [],
        session_id: 'ses_mock42',
        cost_usd: 1.07,
        new_tokens: 49220,
        peak_context: 60000,
        worktrees: [],
        log_path: '/home/op/.canopy/runs/42.log',
        activity: null,
        persona: null,
        persona_digest: null,
        models: {
            status: 'found',
            models: [{ model: 'anthropic/claude-sonnet-4-5', replies: 52, cost_usd: 1.07 }],
            error: null,
        },
    },
]

/** One attention item: the blocked run's question, awaiting a reply. */
export const mockAttention: AttentionItem[] = [
    {
        id: 'a1',
        subject: 'ABC-102',
        ticket_key: 'ABC-102',
        ticket_title: 'Export reports as CSV',
        chore: null,
        repo: null,
        reason: 'awaiting_reply',
        detail: 'message 5: Should the export button be red or blue?',
        since: '2026-10-08T11:56:00Z',
        finding: false,
        pr: null,
    },
]

/** One ticket, started privately and waiting on the operator. */
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
        plan_waits: false,
    },
]

/** One review of a PR, running: it has reported nothing yet. */
export const mockReviews: ReviewSummary[] = [
    {
        id: 5,
        pr_url: 'https://github.com/acme/web/pull/91',
        sha: '9b1d4e7c2a30',
        ticket_key: 'ABC-103',
        title: 'ABC-103: move billing to v2 and drop the v1 client',
        repo: 'web',
        status: 'running',
        state: 'running',
        verdict: null,
        impact: null,
        findings: 0,
        worst: null,
        worst_count: 0,
        started_at: '2026-10-08T12:01:00Z',
        ended_at: null,
        cost_usd: 0.04,
        persona: 'canopy',
        news: false,
        seen: false,
        draft: null,
    },
]

/** One configured chore. */
export const mockChores: ChoreSummary[] = [
    {
        name: 'deps',
        title: 'Dependency advisories',
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
            more_findings: 0,
            session_id: 'ses_chore2',
            cost_usd: 0.26,
            new_tokens: 11960,
            peak_context: 14400,
            log_path: '/home/op/.canopy/chore-runs/deps/2.log',
        },
        due_at: '2026-10-08T14:00:00Z',
        findings: [
            {
                id: 'lodash-advisory',
                title: 'lodash 4.17.20 has a prototype pollution advisory',
                detail: "web's lockfile pins lodash 4.17.20 through an old date picker; 4.17.21 fixes it.",
                link: 'https://github.com/advisories/GHSA-35jh-r3h4-6jhm',
                since: '2026-10-08T08:00:00Z',
                dismissed: false,
            },
        ],
        max_findings: 5,
        more_findings: 0,
        latest_note_id: 8,
        spend: {
            day: { hours: 24, runs: 2, priced: 2, cost_usd: 0.47, mean_usd: 0.235, p99_usd: 0.26, max_usd: 0.26 },
            month: { hours: 720, runs: 4, priced: 3, cost_usd: 0.87, mean_usd: 0.29, p99_usd: 0.4, max_usd: 0.4 },
        },
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

/** Run 45's draft 1 on PR 88, waiting: a reply to alice's thread, `fields` over it. */
export function draft(fields: Partial<Draft> = {}): Draft {
    return {
        run: 45,
        number: 1,
        ticket_key: 'ABC-099',
        kind: 'thread',
        status: 'waiting',
        stance: 'changed',
        comment_id: 2468013579,
        thread_id: 'PRRT_1',
        issue_url: null,
        why: null,
        text: 'Moved it into a `finally`.',
        reaction: null,
        hash: 'cb496d375e04',
        edited: false,
        supersedes_edited: false,
        sent_url: null,
        reacted: null,
        created_at: '2026-10-08T11:38:00Z',
        ...fields,
    }
}

/**
 * Review 5's draft of a review on Carol's PR 14, waiting at its first version: the summary and a finding off the diff
 * in the body, and a comment made from finding 1 on line 15 of the diff's first file, `fields` over it.
 */
export function reviewDraft(fields: Partial<ReviewDraft> = {}): ReviewDraft {
    return {
        status: 'waiting',
        why: null,
        version: 1,
        hash: '3f9a1c27b0de',
        author: 'reviewer',
        channel: null,
        change: "made from review run 5's summary and findings",
        refused: [],
        body: 'The retry works for a 503.\n\n`tests/test_upstream.py`\n\nNo test stops the backoff',
        comments: [
            {
                number: 1,
                path: 'api/upstream.py',
                line: 15,
                text: 'The last 503 is returned as if it were an answer',
                finding: 1,
                file: 0,
                diff_line: 15,
            },
        ],
        max_comments: 30,
        versions: [
            {
                number: 1,
                hash: '3f9a1c27b0de',
                author: 'reviewer',
                channel: null,
                change: "made from review run 5's summary and findings",
                created_at: '2026-10-08T11:30:00Z',
            },
        ],
        moved_head: null,
        published_at: null,
        published_url: null,
        ...fields,
    }
}

/** alice's thread on PR 88, at useSearch.ts:16 on the diff's second file, `fields` over it. */
export function reviewThread(fields: Partial<ReviewThread> = {}): ReviewThread {
    return {
        id: 'PRRT_1',
        path: 'src/search/useSearch.ts',
        line: 16,
        side: 'right',
        outdated: false,
        resolved: false,
        file: 1,
        diff_line: 16,
        comments: [
            {
                id: 2468013579,
                author: 'alice',
                bot: false,
                created_at: '2026-10-08T11:12:00Z',
                body: 'Can it move into a `finally`?',
                url: 'https://github.com/acme/web/pull/88#discussion_r2468013579',
                operator_sent: false,
            },
        ],
        drafts: [draft()],
        ...fields,
    }
}

/** PR 88's threads as the reader last read them, with no diff kept, `fields` over them. */
export function pullRequestThreads(fields: Partial<PullRequestThreads> = {}): PullRequestThreads {
    return {
        url: 'https://github.com/acme/web/pull/88',
        review_replies: 'approve',
        read_at: '2026-10-08T11:42:00Z',
        head_sha: `e3a7d915${'9'.repeat(32)}`,
        diff_run: null,
        diff_head: null,
        diff: null,
        threads: [reviewThread()],
        pr_drafts: [],
        unplaced: [],
        ...fields,
    }
}
