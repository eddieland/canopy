import { describe, expect, it } from 'vitest'

import type { Limit, ReviewSummary, TicketPlans } from '@/api/types'

import {
    choreRunDescription,
    counted,
    pullRequestDescription,
    reviewDescription,
    runDescription,
    tickDescription,
    ticketDescription,
} from './descriptions'

const REVIEW: ReviewSummary = {
    id: 4,
    pr_url: 'https://github.com/acme/web/pull/88',
    sha: `9b2f4c61${'3'.repeat(32)}`,
    ticket_key: 'ABC-099',
    repo: 'web',
    status: 'done',
    state: 'done',
    verdict: 'findings',
    impact: 'normal',
    findings: 3,
    worst: 'major',
    worst_count: 1,
    started_at: '2026-10-08T11:02:00Z',
    ended_at: '2026-10-08T11:04:00Z',
    cost_usd: 0.24,
    seen: true,
}

describe('runDescription', () => {
    it('says how the run ended and its kind, a resume with its reasons', () => {
        expect(runDescription({ status: 'done', kind: 'implement', reasons: [] })).toBe('done · implement')
        expect(runDescription({ status: 'blocked', kind: 'address_review', reasons: [] })).toBe(
            'blocked · address review',
        )
        expect(runDescription({ status: 'running', kind: 'resume', reasons: ['ci', 'review'] })).toBe(
            'running · resume (ci, review)',
        )
    })
})

describe('reviewDescription', () => {
    it('says how it ended, and leaves its verdict and commit to its panel', () => {
        expect(reviewDescription(REVIEW)).toBe('done')
        expect(reviewDescription({ status: 'running' })).toBe('running')
    })
})

describe('pullRequestDescription', () => {
    const OURS = { ticket_key: 'ABC-099', running_run: null, latest_review: REVIEW }
    const limit = (runs: number): Limit => ({
        kind: 'review',
        repo: 'web',
        pr_url: REVIEW.pr_url,
        runs,
        granted: 0,
        limit: 2,
    })

    it('leads with its latest review and that review verdict, not its ticket or how many reviews it has', () => {
        expect(pullRequestDescription(OURS, limit(1))).toBe('review:4 3 findings, 1 major')
        expect(pullRequestDescription({ ...OURS, latest_review: { ...REVIEW, verdict: 'clean' } }, limit(1))).toBe(
            'review:4 clean',
        )
    })

    it('says a review still running is reviewing', () => {
        const running = { ...REVIEW, status: 'running', state: 'running', verdict: null } as const
        expect(pullRequestDescription({ ...OURS, latest_review: running }, limit(1))).toBe('review:4 reviewing')
    })

    it('says when canopy has not reviewed it', () => {
        expect(pullRequestDescription({ ...OURS, latest_review: null }, null)).toBe('not reviewed')
    })

    it('says it is at its review limit while it is', () => {
        expect(pullRequestDescription(OURS, limit(2))).toBe('review:4 3 findings, 1 major · at its review limit')
    })

    it('names the run working it now', () => {
        expect(pullRequestDescription({ ...OURS, running_run: 41 }, limit(1))).toBe(
            'review:4 3 findings, 1 major · run:41 running',
        )
    })

    it('says why a PR has no ticket, since its identity panel leaves the field out', () => {
        expect(pullRequestDescription({ ...OURS, ticket_key: null }, limit(1))).toBe(
            'review:4 3 findings, 1 major · canopy only reviews it',
        )
        expect(pullRequestDescription({ ticket_key: null, running_run: null, latest_review: null }, null)).toBe(
            'not reviewed · canopy only reviews it',
        )
    })
})

describe('choreRunDescription', () => {
    it('counts the findings of a run that ended ok', () => {
        expect(choreRunDescription({ status: 'ok', more_findings: 0 }, 2)).toBe('ok · 2 findings')
        expect(choreRunDescription({ status: 'ok', more_findings: 0 }, 0)).toBe('ok · no findings')
    })

    it('says how many more a run found than it listed, past its max_findings', () => {
        expect(choreRunDescription({ status: 'ok', more_findings: 7 }, 5)).toBe('ok · 5 findings · 7 not listed')
    })

    it('says only how a run ended that reported nothing', () => {
        expect(choreRunDescription({ status: 'timeout', more_findings: 0 }, 0)).toBe('timeout')
    })
})

describe('tickDescription', () => {
    it('says how it ended, its decisions, and what woke it', () => {
        expect(tickDescription({ status: 'ok', woken_by: 'timer' }, 4)).toBe('ok · 4 decisions · woken by timer')
        expect(tickDescription({ status: 'failed', woken_by: null }, 0)).toBe('failed · no decisions')
    })
})

describe('ticketDescription', () => {
    const IDLE = { running_run: null, awaiting: null }
    const NO_PLAN: TicketPlans = {
        changes_asked: null,
        needed: false,
        newest: null,
        planning: null,
        plans: [],
        policy: 'off',
        setting: null,
        threads: [],
    }

    it('says the run working it and the question waiting on you, and nothing for a ticket at rest', () => {
        expect(ticketDescription({ running_run: 41, awaiting: 3 }, NO_PLAN)).toBe('run:41 running · waiting on you')
        expect(ticketDescription(IDLE, NO_PLAN)).toBe('')
        expect(ticketDescription(IDLE, undefined)).toBe('')
    })

    it('says a plan is needed only while it has none and needs one', () => {
        expect(ticketDescription(IDLE, { ...NO_PLAN, needed: true })).toBe('plan needed')
    })

    it("says its plan's status, as its card's chip says it", () => {
        const plan = {
            id: 2,
            run_id: 41,
            status: 'proposed',
            created_at: '2026-10-08T11:00:00Z',
            approved_at: null,
            approved_channel: null,
            approved_reason: null,
        } as const
        const file = {
            plan,
            path: '/state/plans/ABC-1/41.md',
            text: '# Plan\n',
            problem: null,
            sha256: 'abc',
            edited: false,
            changed_since_approval: false,
        }
        const plans: TicketPlans = { ...NO_PLAN, needed: true, plans: [plan], newest: file }
        expect(ticketDescription(IDLE, plans)).toBe('plan waiting on you')
        expect(ticketDescription(IDLE, { ...plans, planning: 7 })).toBe('plan proposed')
        const approved = { ...plan, status: 'approved', approved_at: '2026-10-08T11:30:00Z' } as const
        expect(ticketDescription(IDLE, { ...plans, newest: { ...file, plan: approved } })).toBe('plan approved')
    })
})

describe('counted', () => {
    it('says none, one, or many', () => {
        expect(counted(0, 'run')).toBe('no runs')
        expect(counted(1, 'run')).toBe('1 run')
        expect(counted(12, 'run')).toBe('12 runs')
    })
})
