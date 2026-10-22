import { describe, expect, it } from 'vitest'

import type { ReviewFinding, ReviewSummary } from '@/api/types'

import { placeFindings, shortSha, verdictText, verdictTone } from './reviews'

function finding(title: string, file: number | null, line: number | null): ReviewFinding {
    return { severity: 'minor', title, location: '', detail: '', file, line, dismissed: false }
}

const REVIEW: ReviewSummary = {
    id: 4,
    pr_url: 'https://github.com/acme/web/pull/88',
    sha: `9b2f4c61${'3'.repeat(32)}`,
    ticket_key: 'ABC-099',
    title: null,
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
    persona: 'canopy',
    news: true,
    seen: true,
    draft: null,
}

describe('placeFindings', () => {
    it('puts a finding on its line, its file, or elsewhere, numbered in the review order', () => {
        const placed = placeFindings(
            [finding('a', 1, 15), finding('b', 0, null), finding('c', null, null), finding('d', 1, 15)],
            true,
        )
        expect(
            placed.lines
                .get(1)
                ?.get(15)
                ?.map((f) => [f.n, f.finding.title]),
        ).toEqual([
            [1, 'a'],
            [4, 'd'],
        ])
        expect(placed.files.get(0)?.map((f) => f.n)).toEqual([2])
        expect(placed.elsewhere.map((f) => f.n)).toEqual([3])
    })

    it('puts every finding elsewhere when there is no diff', () => {
        const placed = placeFindings([finding('a', 1, 15), finding('b', 0, null)], false)
        expect(placed.elsewhere.map((f) => f.n)).toEqual([1, 2])
        expect(placed.lines.size + placed.files.size).toBe(0)
    })
})

describe('verdictText', () => {
    it('says what a review found, or why it has no verdict', () => {
        expect(verdictText(REVIEW)).toBe('3 findings, 1 major')
        expect(verdictText({ ...REVIEW, worst: 'blocking', worst_count: 2 })).toBe('3 findings, 2 blocking')
        // Every finding as bad as the worst: one word says both.
        expect(verdictText({ ...REVIEW, findings: 1 })).toBe('1 major finding')
        expect(verdictText({ ...REVIEW, worst: 'minor', worst_count: 3 })).toBe('3 minor findings')
        expect(verdictText({ ...REVIEW, findings: 2, worst: null, worst_count: 0 })).toBe('2 findings')
        expect(verdictText({ ...REVIEW, verdict: 'clean', findings: 0 })).toBe('clean')
        expect(verdictText({ ...REVIEW, verdict: null, state: 'failed', findings: 0 })).toBe('no verdict')
        expect(verdictText({ ...REVIEW, verdict: null, state: 'running', findings: 0 })).toBe('reviewing')
    })
})

describe('verdictTone', () => {
    it('colors a verdict by its worst finding, not by how its run ended', () => {
        expect(verdictTone({ worst: 'blocking' })).toBe('text-status-failed')
        expect(verdictTone({ worst: 'major' })).toBe('text-status-blocked')
        expect(verdictTone({ worst: 'minor' })).toBe('')
        expect(verdictTone({ worst: null })).toBe('')
    })
})

it('shortens a commit to 7 characters', () => {
    expect(shortSha(REVIEW.sha)).toBe('9b2f4c6')
})
