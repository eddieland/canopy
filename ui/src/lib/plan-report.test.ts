import { describe, expect, it } from 'vitest'

import type { PlansGroup } from '@/api/types'

import {
    changesText,
    lengthLinesText,
    lengthText,
    levelText,
    measuredText,
    notProseText,
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
        median_lines: 40,
        median_words: 400,
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

    it('names a level, a share of PRs resumed, and a length bucket in pages, its lines for the hover', () => {
        expect([levelText('strict'), levelText(null)]).toEqual(['strict', 'not recorded'])
        expect([resumedText(group(2, 1)), resumedText(group(0, 0))]).toEqual(['1 of 2', '–'])
        const buckets = [
            { low: 0, high: 50 },
            { low: 50, high: 100 },
            { low: 200, high: 300 },
            { low: 300, high: null },
        ]
        expect(buckets.map((b) => lengthText(b, 50))).toEqual([
            'under 1 page',
            '1–2 pages',
            '4–6 pages',
            '6 pages and up',
        ])
        expect(lengthText({ low: 50, high: null }, 50)).toBe('1 page and up')
        expect(buckets.map((b) => lengthLinesText(b))).toEqual([
            'under 50 lines',
            '50–100 lines',
            '200–300 lines',
            '300 lines and up',
        ])
    })

    it('reads a length as pages to the nearest half, never under a half', () => {
        expect([0, 24, 38, 50, 74, 76, 100, 340].map((n) => pagesText(n, 50))).toEqual([
            '≈ ½ page',
            '≈ ½ page',
            '≈ 1 page',
            '≈ 1 page',
            '≈ 1½ pages',
            '≈ 1½ pages',
            '≈ 2 pages',
            '≈ 7 pages',
        ])
    })

    it("says what a plan's length is made of, and what of it is not prose", () => {
        expect(measuredText({ lines: 161, words: 1622 }, 9_341)).toBe('161 lines · 1,622 words · 9.1 KiB')
        expect(notProseText({ code_blocks: 2, tables: 1, diagrams: 1 })).toBe('2 code · 1 table · 1 diagram')
        expect(notProseText({ code_blocks: 0, tables: 0, diagrams: 0 })).toBe('')
    })

    it('says what changed before an approval, and why the resumes after ran', () => {
        expect(changesText({ edited: true, comments: 2, earlier: 1 })).toBe('edited, 2 comments, after 1 sent back')
        expect(changesText({ edited: false, comments: 0, earlier: 0 })).toBe('')
        expect(reasonsText({ ci: 1, review: 2 })).toBe('ci 1, review 2')
        expect(reasonsText({})).toBe('')
    })
})
