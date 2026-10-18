import { describe, expect, it } from 'vitest'

import type { Limit, ReviewSummary } from '@/api/types'

import {
    choreRunDescription,
    counted,
    pullRequestDescription,
    reviewDescription,
    runDescription,
    tickDescription,
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
}

describe('runDescription', () => {
    it('says how the run ended, its kind, and its ticket', () => {
        expect(runDescription({ status: 'done', kind: 'implement', ticket_key: 'ABC-099' })).toBe(
            'done · implement · ABC-099',
        )
        expect(runDescription({ status: 'blocked', kind: 'address_review', ticket_key: 'ABC-102' })).toBe(
            'blocked · address review · ABC-102',
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
    const LIMIT: Limit = {
        kind: 'review',
        repo: 'web',
        pr_url: REVIEW.pr_url,
        runs: 1,
        granted: 0,
        limit: 2,
    }

    it('leads with its latest review and that review’s verdict, and leaves out its ticket and review count', () => {
        const pr = { ticket_key: 'ABC-099', running_run: null, latest_review: REVIEW }
        expect(pullRequestDescription(pr, LIMIT)).toBe('review:4 3 findings, 1 major')
        expect(pullRequestDescription({ ...pr, latest_review: { ...REVIEW, verdict: 'clean' } }, LIMIT)).toBe(
            'review:4 clean',
        )
    })

    it('says a review still running is reviewing, and one that reported no verdict so', () => {
        const pr = { ticket_key: 'ABC-103', running_run: null }
        const running = { ...REVIEW, id: 5, status: 'running', state: 'running', verdict: null } as const
        expect(pullRequestDescription({ ...pr, latest_review: running }, LIMIT)).toBe('review:5 reviewing')
        const failed = { ...REVIEW, id: 3, status: 'crashed', state: 'failed', verdict: null } as const
        expect(pullRequestDescription({ ...pr, latest_review: failed }, LIMIT)).toBe('review:3 no verdict')
    })

    it('says a PR canopy has not reviewed is not reviewed', () => {
        expect(pullRequestDescription({ ticket_key: 'ABC-099', running_run: null, latest_review: null }, null)).toBe(
            'not reviewed',
        )
    })

    it('says a PR at its review limit is, while it is', () => {
        const pr = { ticket_key: 'ABC-099', running_run: null, latest_review: REVIEW }
        expect(pullRequestDescription(pr, { ...LIMIT, runs: 2 })).toBe(
            'review:4 3 findings, 1 major · at its review limit',
        )
        expect(pullRequestDescription(pr, { ...LIMIT, runs: 2, granted: 1, limit: 3 })).toBe(
            'review:4 3 findings, 1 major',
        )
    })

    it('names the run working it now', () => {
        expect(pullRequestDescription({ ticket_key: 'ABC-099', running_run: 41, latest_review: REVIEW }, LIMIT)).toBe(
            'review:4 3 findings, 1 major · run:41 running',
        )
    })

    it('says why a PR has no ticket, once, since its ticket field leaves the reason out', () => {
        const clean = { ...REVIEW, id: 2, ticket_key: null, verdict: 'clean', findings: 0, worst: null } as const
        expect(pullRequestDescription({ ticket_key: null, running_run: null, latest_review: clean }, LIMIT)).toBe(
            'review:2 clean · canopy only reviews it',
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

describe('counted', () => {
    it('says none, one, or many', () => {
        expect(counted(0, 'run')).toBe('no runs')
        expect(counted(1, 'run')).toBe('1 run')
        expect(counted(12, 'run')).toBe('12 runs')
    })
})
