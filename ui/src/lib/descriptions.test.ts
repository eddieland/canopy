import { describe, expect, it } from 'vitest'

import type { ReviewSummary } from '@/api/types'

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
    it('says how it ended, its verdict, and the commit it read', () => {
        expect(reviewDescription(REVIEW)).toBe('done · 3 findings, 1 major · 9b2f4c6')
    })

    it('leaves out the verdict while it reviews', () => {
        expect(reviewDescription({ ...REVIEW, status: 'running', state: 'running', verdict: null })).toBe(
            'running · 9b2f4c6',
        )
    })
})

describe('pullRequestDescription', () => {
    it('names its ticket, its reviews, and the run working it', () => {
        expect(pullRequestDescription({ ticket_key: 'ABC-099', running_run: 41 }, 2)).toBe(
            'ABC-099 · 2 reviews · run:41 running',
        )
    })

    it('says why a PR has no ticket', () => {
        expect(pullRequestDescription({ ticket_key: null, running_run: null }, 1)).toBe(
            'canopy only reviews it · 1 review',
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
