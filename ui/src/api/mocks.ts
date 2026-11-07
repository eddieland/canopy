// Typed fixtures for unit tests, a few of the rows canopy/serve/mock/ seeds its journal with. The dev server and the
// end-to-end tests get the whole seeded journal from `python -m canopy.serve --mock`.
import type {
    Attachments,
    AttentionItem,
    Capacity,
    ChoreSummary,
    Draft,
    EpicDetail,
    EpicPlans,
    EpicSummary,
    FeedbackPlan,
    FeedbackPlanItem,
    HostResources,
    PullRequestThreads,
    ReportMonth,
    ReportTicket,
    ReportTokens,
    ReviewDraft,
    ReviewSummary,
    ReviewThread,
    Run,
    SearchHit,
    TaskRun,
    TaskSummary,
    TicketSummary,
} from './types'

/** A ticket's or a task's attachments while it has none, under the default limits (DESIGN §22). */
export const mockNoAttachments: Attachments = {
    items: [],
    max_files: 5,
    max_file_bytes: 512 * 1024,
    max_total_bytes: 1024 * 1024,
}

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
        worktrees: [
            {
                repo: 'web',
                path: '.treehouse/web-3f9c2a1b/1/web',
                absolute: '/home/op/acme/.treehouse/web-3f9c2a1b/1/web',
            },
        ],
        log_path: '/home/op/.canopy/runs/41.log',
        activity: { tool: 'bash', did: 'npm test -- login', at: '2026-10-08T12:27:00Z' },
        card: {
            summary: 'The SSO callback is in and its tests pass; wiring the login button next.',
            now: 'running the login tests',
            done: [{ step: 'add the SSO callback', proof: 'tests pass: 12/12' }],
            next: ['wire the login button', 'push'],
            stuck: null,
            at: '2026-10-08T12:24:00Z',
            calls_since: 3,
            stale: false,
            stale_at: '2026-10-08T12:34:00Z',
            steps: [],
            percent: null,
            stage: null,
            question: null,
        },
        persona: 'canopy',
        persona_digest: '6c1f0a3e9b2d4c5a7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d',
        model: null,
        models: { status: 'running', models: [], error: null },
        feedback_plan: null,
        checklist: [],
        checklist_stretches: [],
        checklist_stretches_left_out: 0,
        messages: [],
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
        card: null,
        persona: null,
        persona_digest: null,
        model: null,
        models: {
            status: 'found',
            models: [{ model: 'anthropic/claude-sonnet-4-5', replies: 52, cost_usd: 1.07 }],
            error: null,
        },
        feedback_plan: null,
        checklist: [],
        checklist_stretches: [],
        checklist_stretches_left_out: 0,
        messages: [],
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
        task: null,
        epic: null,
        run: null,
        review: null,
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
        feedback_plan: null,
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
        author: 'op',
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
        request_id: null,
        news: false,
        seen: false,
        draft: null,
        served: [],
        asks_you: false,
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
            served: [],
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

/** A run of a task, ended done in web, with whatever `fields` replace. */
export function mockTaskRun(fields: Partial<TaskRun> = {}): TaskRun {
    return {
        id: 1,
        status: 'done',
        state: 'done',
        started_at: '2026-10-08T05:02:00Z',
        ended_at: '2026-10-08T05:40:00Z',
        branch: 'agent/task/1',
        head: '5e0b7c2a9d41f3e86a2c4b7d9e1f0a3c5b8d2e4f',
        summary: 'Cut the checkout bundle from 934 kB to 612 kB; filed two tickets for what is left.',
        prs: ['https://github.com/acme/web/pull/97'],
        reported: true,
        session_id: 'ses_task1',
        cost_usd: 2.12,
        new_tokens: 48210,
        peak_context: 61200,
        log_path: '.canopy/task-runs/1.log',
        served: [],
        card: null,
        ...fields,
    }
}

/**
 * The mock journal's four epics, the newest first as `GET /api/epics` sends them: stopped, as soon as it was
 * submitted; planning; proposed; and approved.
 */
export const mockEpics: EpicSummary[] = [
    {
        id: 4,
        text: "Give the web app a dark theme that follows the system's setting.",
        repos: ['web'],
        project: 'ABC',
        tracker_epic: null,
        channel: 'web',
        submitted_at: '2026-10-08T11:59:00Z',
        stopped_at: '2026-10-08T11:59:00Z',
        standing: 'stopped',
        members: 0,
        planned: false,
        entries: null,
        entries_with_members: 0,
    },
    {
        id: 3,
        text: 'Replace the feature flags read from the `flags` table with the flags service, in api and web.',
        repos: ['api', 'web'],
        project: null,
        tracker_epic: null,
        channel: 'cli',
        submitted_at: '2026-10-08T11:57:00Z',
        stopped_at: null,
        standing: 'planning',
        members: 0,
        planned: false,
        entries: null,
        entries_with_members: 0,
    },
    {
        id: 2,
        text:
            "Show a customer's order history in the mobile app when it is offline, as of their last sync. The web " +
            'account page has the same list; keep the two in step.',
        repos: ['mobile', 'web'],
        project: 'ABC',
        tracker_epic: null,
        channel: 'web',
        submitted_at: '2026-10-08T07:40:00Z',
        stopped_at: null,
        standing: 'proposed',
        members: 0,
        planned: true,
        entries: 3,
        entries_with_members: 0,
    },
    {
        id: 1,
        text:
            'Move billing to the v2 API everywhere it is called, web and mobile both, and retire v1 once nothing ' +
            'reads it.\n\nv2 is down for a minute or two most weeks, so a call that fails should wait and try again ' +
            "rather than show the customer an error. Keep the invoices' numbers exactly as they are.",
        repos: ['api', 'web', 'mobile'],
        project: 'ABC',
        tracker_epic: null,
        channel: 'cli',
        submitted_at: '2026-10-08T00:00:00Z',
        stopped_at: null,
        standing: 'approved',
        members: 3,
        planned: true,
        entries: 4,
        entries_with_members: 2,
    },
]

/** The mock epic numbered `id`, as the list has it. */
function epicOf(id: number): EpicSummary {
    const found = mockEpics.find((epic) => epic.id === id)
    if (found === undefined) {
        throw new Error(`no mock epic:${String(id)}`)
    }
    return found
}

/**
 * The mock journal's four epics as `GET /api/epics/{id}` sends each, oldest first: approved, with members, one of
 * them of no entry; proposed, after the operator's reply; planning, its first plan run at work; and stopped before
 * any plan run of it started.
 */
export const mockEpicDetails: EpicDetail[] = [
    {
        epic: epicOf(1),
        members: [
            {
                key: 'ABC-103',
                title: 'Move billing to the v2 API',
                entries: ['B1'],
                dropped: [],
                added_at: '2026-10-08T07:10:00Z',
                added_channel: 'cli',
                phase: 'review_pending',
                prs: ['https://github.com/acme/web/pull/91'],
                latest_run: {
                    id: 38,
                    kind: 'implement',
                    status: 'done',
                    state: 'done',
                },
            },
            {
                key: 'ABC-104',
                title: null,
                entries: ['B2'],
                dropped: [],
                added_at: '2026-10-08T07:15:00Z',
                added_channel: 'cli',
                phase: 'ci_red',
                prs: [],
                latest_run: {
                    id: 43,
                    kind: 'resume',
                    status: 'running',
                    state: 'running',
                },
            },
            {
                key: 'ABC-100',
                title: 'Fix the flaky checkout test',
                entries: [],
                dropped: [],
                added_at: '2026-10-08T08:40:00Z',
                added_channel: 'cli',
                phase: 'ci_red',
                prs: [],
                latest_run: {
                    id: 40,
                    kind: 'fix-ci',
                    status: 'failed',
                    state: 'failed',
                },
            },
        ],
        bound: 8,
        max_plan_attempts: 3,
        runs: [
            {
                id: 1,
                status: 'done',
                state: 'done',
                started_at: '2026-10-08T00:05:00Z',
                ended_at: '2026-10-08T00:30:00Z',
                summary: 'A plan of four entries; B4 is trivial.',
                question: null,
                plan_id: 1,
                model: null,
                cost_usd: null,
            },
        ],
        messages: [],
        plan: {
            id: 1,
            run_id: 1,
            status: 'approved',
            created_at: '2026-10-08T00:30:00Z',
            approved_at: '2026-10-08T02:00:00Z',
            approved_channel: 'web',
        },
        outline: {
            source: 'approved',
            plan_id: 1,
            run_id: 1,
            problem: null,
            requirements: [
                {
                    id: 'R1',
                    text: 'Every billing call in web and mobile goes to the v2 endpoint.',
                },
                {
                    id: 'R2',
                    text:
                        'A billing call that fails while v2 is down is queued and retried, never shown to the ' +
                        'customer as an error.',
                },
                {
                    id: 'R3',
                    text: 'Nothing reads the `billing_v1` flag, and api no longer serves it.',
                },
            ],
            contracts: [
                {
                    id: 'C1',
                    text:
                        "`BillingClient`, the v2 client: `listInvoices`, `charge`, and `refund`, each returning v2's " +
                        "types unchanged. web provides it; mobile's screens and the retry queue use it.",
                },
            ],
            entries: [
                {
                    id: 'B1',
                    title: 'A v2 billing client in web',
                    covers: ['R1'],
                    provides: ['C1'],
                    uses: [],
                    repos: ['web'],
                    after: [],
                    trivial: null,
                    members: ['ABC-103'],
                },
                {
                    id: 'B2',
                    title: 'Retry failed billing calls from a queue',
                    covers: ['R2'],
                    provides: [],
                    uses: ['C1'],
                    repos: ['mobile', 'web'],
                    after: ['B1'],
                    trivial: null,
                    members: ['ABC-104'],
                },
                {
                    id: 'B3',
                    title: "Mobile's billing screens on v2",
                    covers: ['R1'],
                    provides: [],
                    uses: ['C1'],
                    repos: ['mobile'],
                    after: ['B1'],
                    trivial: null,
                    members: [],
                },
                {
                    id: 'B4',
                    title: 'Retire the v1 billing flag',
                    covers: ['R3'],
                    provides: [],
                    uses: [],
                    repos: ['api'],
                    after: ['B1', 'B3'],
                    trivial: 'it deletes one flag and its read, which nothing calls once B1 and B3 ship',
                    members: [],
                },
            ],
        },
    },
    {
        epic: epicOf(2),
        members: [],
        bound: 8,
        max_plan_attempts: 3,
        runs: [
            {
                id: 2,
                status: 'done',
                state: 'done',
                started_at: '2026-10-08T07:42:00Z',
                ended_at: '2026-10-08T08:00:00Z',
                summary: 'A plan of two entries, one per repository.',
                question: null,
                plan_id: 2,
                model: null,
                cost_usd: null,
            },
            {
                id: 3,
                status: 'done',
                state: 'done',
                started_at: '2026-10-08T08:50:00Z',
                ended_at: '2026-10-08T09:10:00Z',
                summary: 'Kept it to mobile, and added clearing at sign-out.',
                question: null,
                plan_id: 3,
                model: null,
                cost_usd: null,
            },
        ],
        messages: [
            {
                id: 20,
                at: '2026-10-08T08:40:00Z',
                source: 'operator',
                kind: 'reply',
                channel: 'web',
                run_id: null,
                task_run_id: null,
                answers: null,
                body:
                    'Drop the web half: the account page already reads the same API, so the two cannot drift. Keep ' +
                    'it to mobile, and say how the local copy is cleared when the customer signs out.',
                comment: null,
            },
        ],
        plan: {
            id: 3,
            run_id: 3,
            status: 'proposed',
            created_at: '2026-10-08T09:10:00Z',
            approved_at: null,
            approved_channel: null,
        },
        outline: {
            source: 'proposed',
            plan_id: 3,
            run_id: 3,
            problem: null,
            requirements: [
                {
                    id: 'R1',
                    text: 'The mobile app shows the order history offline, as of its last sync.',
                },
                {
                    id: 'R2',
                    text: 'Signing out clears the local copy before the sign-in screen shows.',
                },
            ],
            contracts: [
                {
                    id: 'C1',
                    text: '`OrderStore`: `orders()`, `sync()`, and `clear()`, the local copy the screens read.',
                },
            ],
            entries: [
                {
                    id: 'B1',
                    title: 'A local copy of the order history',
                    covers: ['R1'],
                    provides: ['C1'],
                    uses: [],
                    repos: ['mobile'],
                    after: [],
                    trivial: null,
                    members: [],
                },
                {
                    id: 'B2',
                    title: 'The order screens read the local copy',
                    covers: ['R1'],
                    provides: [],
                    uses: ['C1'],
                    repos: ['mobile'],
                    after: ['B1'],
                    trivial: null,
                    members: [],
                },
                {
                    id: 'B3',
                    title: 'Clear the local copy at sign-out',
                    covers: ['R2'],
                    provides: [],
                    uses: ['C1'],
                    repos: ['mobile'],
                    after: ['B1'],
                    trivial: null,
                    members: [],
                },
            ],
        },
    },
    {
        epic: epicOf(3),
        members: [],
        bound: 8,
        max_plan_attempts: 3,
        runs: [
            {
                id: 4,
                status: 'running',
                state: 'running',
                started_at: '2026-10-08T11:58:00Z',
                ended_at: null,
                summary: null,
                question: null,
                plan_id: null,
                model: null,
                cost_usd: null,
            },
        ],
        messages: [],
        plan: null,
        outline: null,
    },
    {
        epic: epicOf(4),
        members: [],
        bound: 8,
        max_plan_attempts: 3,
        runs: [],
        messages: [],
        plan: null,
        outline: null,
    },
]

/** Epic 1's plan as its planner wrote it, and as the operator approved it. */
const BILLING_PLAN = `# Billing on v2

## Goal

Every billing call goes to v2, a failed call is retried from a queue, and the v1 flag is gone.

## Requirements

- **R1.** Every billing call in web and mobile goes to the v2 endpoint.
- **R2.** A billing call that fails while v2 is down is queued and retried, never shown to the customer as an error.
- **R3.** Nothing reads the \`billing_v1\` flag, and api no longer serves it.

## Breakdown

### B1. A v2 billing client in web

- Covers: R1
- Provides: C1
`

/** Epic 2's first plan, which the operator's reply superseded. */
const OFFLINE_FIRST = `# Offline order history

## Goal

The order history reads from a local copy when the app is offline.

## Decisions

- Sync on launch and on pull to refresh only.
`

/** Epic 2's second plan, written after the reply, which waits on the operator. */
const OFFLINE_SECOND = `# Offline order history

## Goal

The mobile app's order history reads from a local copy when it is offline, and the copy goes when its customer does.

## Decisions

- The web account page is left as it is: it reads the same API the copy syncs from.
`

/**
 * The mock journal's three epics' plans as `GET /api/epics/{id}/plans` sends each, the oldest plan first: epic 1's
 * approved plan; epic 2's superseded plan, then the proposed one; and epic 3's none, its plan run at work.
 */
export const mockEpicPlans: EpicPlans[] = [
    {
        epic_id: 1,
        planning: null,
        changes_asked: null,
        plans: [
            {
                plan: mockEpicDetails[0]?.plan ?? missing('epic 1 plan'),
                path: '.canopy/plans/epics/1/run-1.md',
                text: BILLING_PLAN,
                problem: null,
                sha256: '9f2c4e81b07d3a65c1e8f4a2d9b0c7e3f6a1d4b8e2c5f9a07b3d6e1c4f8a2b5d',
                edited: false,
                changed_since_approval: false,
            },
        ],
    },
    {
        epic_id: 2,
        planning: null,
        changes_asked: null,
        plans: [
            {
                plan: {
                    id: 2,
                    run_id: 2,
                    status: 'superseded',
                    created_at: '2026-10-08T08:00:00Z',
                    approved_at: null,
                    approved_channel: null,
                },
                path: '.canopy/plans/epics/2/run-2.md',
                text: OFFLINE_FIRST,
                problem: null,
                sha256: '4b7e1d9a3c6f0e2b8d5a1c4f7e0b3d6a9c2f5e8b1d4a7c0f3e6b9d2a5c8f1e4b',
                edited: false,
                changed_since_approval: false,
            },
            {
                plan: mockEpicDetails[1]?.plan ?? missing('epic 2 plan'),
                path: '.canopy/plans/epics/2/run-3.md',
                text: OFFLINE_SECOND,
                problem: null,
                sha256: 'd1a4c7f0e3b6d9a2c5f8e1b4d7a0c3f6e9b2d5a8c1f4e7b0d3a6c9f2e5b8d1a4',
                edited: false,
                changed_since_approval: false,
            },
        ],
    },
    { epic_id: 3, planning: 4, plans: [], changes_asked: null },
    { epic_id: 4, planning: null, plans: [], changes_asked: null },
]

// A mock that should be there and is not: a test's mistake, said as one.
function missing(what: string): never {
    throw new Error(`no mock ${what}`)
}

/** Four tasks, the newest first as `GET /api/tasks` sends them: queued, running, waiting on a reply, and done. */
export const mockTasks: TaskSummary[] = [
    {
        id: 7,
        text: 'List the endpoints that still accept API keys in the query string.',
        repo: 'api',
        project: null,
        branch: 'agent/task/7',
        channel: 'cli',
        submitted_at: '2026-10-08T11:59:00Z',
        stopped_at: null,
        standing: 'queued',
        question_id: null,
        latest: null,
        runs: 0,
    },
    {
        id: 6,
        text: "Add a dark launch screen to match the app's theme.",
        repo: 'mobile',
        project: null,
        branch: 'agent/task/6',
        channel: 'cli',
        submitted_at: '2026-10-08T11:58:00Z',
        stopped_at: null,
        standing: 'running',
        question_id: null,
        latest: mockTaskRun({
            id: 8,
            status: 'running',
            state: 'running',
            started_at: '2026-10-08T11:58:30Z',
            ended_at: null,
            branch: 'agent/task/6',
            head: null,
            summary: null,
            prs: [],
            reported: false,
            cost_usd: 0.31,
        }),
        runs: 1,
    },
    {
        id: 4,
        text: 'Rename the `billing_v1` feature flag to `billing_legacy` everywhere it is read.',
        repo: 'web',
        project: 'ABC',
        branch: 'agent/task/4',
        channel: 'cli',
        submitted_at: '2026-10-08T11:20:00Z',
        stopped_at: null,
        standing: 'awaiting_reply',
        question_id: 41,
        latest: mockTaskRun({
            id: 5,
            status: 'blocked',
            state: 'blocked',
            started_at: '2026-10-08T11:21:00Z',
            ended_at: '2026-10-08T11:34:00Z',
            branch: 'agent/task/4',
            head: null,
            summary: 'The flag is also read by the billing worker in api; rename it there too?',
            prs: [],
            reported: false,
            cost_usd: 0.44,
        }),
        runs: 1,
    },
    {
        id: 1,
        text: "The checkout page's bundle grew past 900 kB.\n\nFind out what grew and cut it back.",
        repo: 'web',
        project: 'ABC',
        branch: 'agent/task/1',
        channel: 'web',
        submitted_at: '2026-10-08T05:00:00Z',
        stopped_at: null,
        standing: 'done',
        question_id: null,
        latest: mockTaskRun(),
        runs: 1,
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
        task_id: null,
        task_title: null,
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
        from_plan: null,
        ...fields,
    }
}

/**
 * Review 5's draft of a review on Carol's PR 14, waiting at its first version: the reviewer's body and a finding off
 * the diff in the body, and a comment made from finding 1 on line 15 of the diff's first file, `fields` over it.
 */
export function reviewDraft(fields: Partial<ReviewDraft> = {}): ReviewDraft {
    return {
        status: 'waiting',
        why: null,
        version: 1,
        hash: '3f9a1c27b0de',
        author: 'reviewer',
        channel: null,
        change: "made from review run 5's body and findings",
        refused: [],
        body:
            "Could the client's own retry transport do this, rather than a loop of our own?\n\n" +
            '`tests/test_upstream.py`\n\nNo test stops the backoff',
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
        in_body: [3],
        versions: [
            {
                number: 1,
                hash: '3f9a1c27b0de',
                author: 'reviewer',
                channel: null,
                change: "made from review run 5's body and findings",
                created_at: '2026-10-08T11:30:00Z',
            },
        ],
        pr_author: 'carol',
        moved_head: null,
        published_at: null,
        published_url: null,
        notes: [],
        revisions: [],
        revision_limit: 3,
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
        feedback_plan: null,
        ...fields,
    }
}

/** Item 2 of run 46's feedback plan for ABC-099: a change for alice's thread on PR 88, `fields` over it. */
export function feedbackPlanItem(fields: Partial<FeedbackPlanItem> = {}): FeedbackPlanItem {
    return {
        number: 2,
        pr_url: 'https://github.com/acme/web/pull/88',
        item: 'comment',
        item_id: 2468013579,
        proposal: 'change',
        reply: 'Moved it into a `finally`.',
        left_out: false,
        author: 'alice',
        trusted: true,
        thread_id: 'PRRT_1',
        excerpt: 'Can it move into a `finally`?',
        rationale: 'Move it into a `finally`.',
        url: 'https://github.com/acme/web/pull/88#discussion_r2468013579',
        check: null,
        blocker: null,
        ...fields,
    }
}

/**
 * Run 46's feedback plan for ABC-099, waiting: alice's review to leave, item 1, and her thread to change, item 2,
 * `fields` over it.
 */
export function feedbackPlan(fields: Partial<FeedbackPlan> = {}): FeedbackPlan {
    return {
        id: 1,
        ticket_key: 'ABC-099',
        run: 46,
        created_at: '2026-10-08T11:48:00Z',
        status: 'waiting',
        changes: [],
        stale_shown: false,
        approved_at: null,
        approved_channel: null,
        approved_reason: null,
        approved_message: null,
        spent_run: null,
        path: '/home/op/acme/.canopy/plans/ABC-099/46.md',
        text: '# Feedback plan: ABC-099\n\n### Item 2468013579: change\n\nMove it into a `finally`.\n',
        problem: null,
        items: [
            feedbackPlanItem({
                number: 1,
                item: 'review',
                item_id: 4102337001,
                proposal: 'leave',
                reply: null,
                thread_id: null,
                excerpt: 'Two small things, then good to go.',
                rationale: null,
                url: 'https://github.com/acme/web/pull/88#pullrequestreview-4102337001',
            }),
            feedbackPlanItem(),
        ],
        ...fields,
    }
}

const GIB = 1024 ** 3
const MIB = 1024 ** 2

/** The mock's machine (canopy/serve/mock/host.py), with any fields replaced: nothing on it under pressure. */
export function mockHost(fields: Partial<HostResources> = {}): HostResources {
    return {
        hostname: 'build-box',
        system: 'Linux 6.8.0',
        machine: 'x86_64',
        python: '3.13.1',
        booted_at: '2026-09-29T08:30:00Z',
        read_at: '2026-10-08T12:30:00Z',
        cpu: { cores: 12, load: [2.41, 1.87, 1.52], time: { busy: 1_425_600, total: 9_504_000 } },
        memory: { total: 64 * GIB, available: 23 * GIB + 410 * MIB, swap_total: 8 * GIB, swap_free: 7 * GIB },
        stalled: { memory: 0, io: 0.004 },
        disks: [
            {
                holds: ['workspace', 'journal'],
                path: '/home/operator/acme',
                total: 931 * GIB,
                free: 412 * GIB,
                floor: 2 * GIB,
            },
            { holds: ['temp'], path: '/tmp', total: 32 * GIB, free: 27 * GIB + 300 * MIB, floor: null },
        ],
        process: {
            pid: 48213,
            started_at: '2026-10-08T09:18:00Z',
            rss: 268 * MIB,
            peak_rss: 412 * MIB,
            threads: 19,
            open_files: 61,
            max_open_files: 65536,
        },
        ...fields,
    }
}

/** What a month's model calls were sent and wrote, four fifths of it read from the cache. */
export const mockReportTokens: ReportTokens = {
    input: 1000,
    output: 200,
    reasoning: 50,
    cache_read: 8000,
    cache_write: 1000,
    cache_hit: 0.8,
}

/** A month of the monthly report, `name` as `YYYY-MM`, that cost `cost` and did nothing else unless `fields` say so. */
export function mockReportMonth(name: string, cost: number | null, fields: Partial<ReportMonth> = {}): ReportMonth {
    return {
        month: name,
        since: `${name}-01T00:00:00Z`,
        until: `${name}-28T00:00:00Z`,
        runs: 0,
        cost_usd: cost,
        tokens: mockReportTokens,
        kinds: [],
        outside: {
            sessions: 0,
            cost_usd: null,
            tokens: { input: 0, output: 0, reasoning: 0, cache_read: 0, cache_write: 0, cache_hit: null },
        },
        models: [],
        landed: [],
        closed: 0,
        pull_requests: 0,
        per_landed_usd: null,
        median_iterations: null,
        median_pr_comments: null,
        median_hours_to_land: null,
        median_review_wait_hours: null,
        runs_ended: 0,
        failed: 0,
        failed_cost_usd: null,
        heads: 0,
        green_first: 0,
        first_reviews: 0,
        median_first_review_hours: null,
        ...fields,
    }
}

/** A ticket October 2026 landed, a worker run and five days after it started, with a review three hours in. */
export function mockReportTicket(key: string, fields: Partial<ReportTicket> = {}): ReportTicket {
    return {
        key,
        title: null,
        landed_at: '2026-10-04T11:00:00Z',
        started_at: '2026-09-28T10:00:00Z',
        iterations: 1,
        pr_comments: 0,
        reviews: 1,
        changes_requested: 0,
        cost_usd: null,
        hours_to_land: 125,
        review_wait_hours: 3,
        merged_at: null,
        awaiting_review_at: null,
        pull_requests: [],
        ...fields,
    }
}
