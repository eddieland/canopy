import { describe, expect, it } from 'vitest'

import type { PlansGroup } from '@/api/types'

import {
    changesText,
    lengthBytesText,
    lengthText,
    levelText,
    pagesText,
    plansLine,
    plansWindow,
    reasonsText,
    resumedText,
} from './plan-report'

const OUTCOMES = { planner: 2, as_written: 1, revised: 2, replaced: 2, dropped: 0, waiting: 1 }

function group(implemented: number, withResume: number): PlansGroup {
    return {
        level: 'strict',
        outcome: 'planner',
        plans: implemented,
        median_hours_to_approve: 0,
        median_size: 2000,
        implemented,
        with_resume: withResume,
        resumes: withResume,
        done: implemented,
    }
}

describe('plan report', () => {
    it('offers 30 and 90 days, and drops a window it does not offer', () => {
        expect(plansWindow({ days: '90' })).toEqual({ days: 90 })
        expect(plansWindow({ days: 30 })).toEqual({ days: 30 })
        expect(plansWindow({ days: '7' })).toBeUndefined()
    })

    it("says the window's plans, those approved, and how many of their PRs needed a resume", () => {
        const plans = Array.from({ length: 8 }, () => ({}) as never)
        expect(plansLine({ days: 30, plans, outcomes: OUTCOMES, groups: [group(2, 1), group(3, 1)] })).toBe(
            '8 plans · 5 approved, 2 by the planner · 2 of 5 PRs needed a resume over 30 days',
        )
        // None implemented yet: nothing to say of resumes.
        expect(plansLine({ days: 7, plans: plans.slice(0, 2), outcomes: { waiting: 2 }, groups: [] })).toBe(
            '2 plans · 0 approved, 0 by the planner over 7 days',
        )
        expect(plansLine({ days: 7, plans: [], outcomes: {}, groups: [] })).toBe('no plans over 7 days')
    })

    it('names a level, a share of PRs resumed, and a size bucket in pages, its bytes for the hover', () => {
        expect([levelText('strict'), levelText(null)]).toEqual(['strict', 'not recorded'])
        expect([resumedText(group(2, 1)), resumedText(group(0, 0))]).toEqual(['1 of 2', '–'])
        const buckets = [
            { low: 0, high: 3_000 },
            { low: 3_000, high: 6_000 },
            { low: 12_000, high: null },
        ]
        expect(buckets.map((b) => lengthText(b, 3_000))).toEqual(['under 1 page', '1–2 pages', '4 pages and up'])
        expect(lengthText({ low: 3_000, high: null }, 3_000)).toBe('1 page and up')
        expect(buckets.map((b) => lengthBytesText(b))).toEqual(['under 2.9 KiB', '2.9–5.9 KiB', '11.7 KiB and up'])
    })

    it('reads a size as pages to the nearest half, never under a half', () => {
        expect([0, 1_400, 1_600, 3_000, 4_400, 4_600, 6_000, 20_000].map((s) => pagesText(s, 3_000))).toEqual([
            '≈ ½ page',
            '≈ ½ page',
            '≈ ½ page',
            '≈ 1 page',
            '≈ 1½ pages',
            '≈ 1½ pages',
            '≈ 2 pages',
            '≈ 6½ pages',
        ])
    })

    it('says what changed before an approval, and why the resumes after ran', () => {
        expect(changesText({ edited: true, comments: 2, earlier: 1 })).toBe('edited, 2 comments, after 1 sent back')
        expect(changesText({ edited: false, comments: 0, earlier: 0 })).toBe('')
        expect(reasonsText({ ci: 1, review: 2 })).toBe('ci 1, review 2')
        expect(reasonsText({})).toBe('')
    })
})
