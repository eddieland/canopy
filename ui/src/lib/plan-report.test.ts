import { describe, expect, it } from 'vitest'

import type { PlansGroup } from '@/api/types'

import { changesText, lengthText, levelText, plansLine, plansWindow, reasonsText, resumedText } from './plan-report'

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

    it('names a level, a share of PRs resumed, and a size bucket', () => {
        expect([levelText('strict'), levelText(null)]).toEqual(['strict', 'not recorded'])
        expect([resumedText(group(2, 1)), resumedText(group(0, 0))]).toEqual(['1 of 2', '–'])
        expect([
            lengthText({ low: 0, high: 4096 }),
            lengthText({ low: 4096, high: 8192 }),
            lengthText({ low: 16_384, high: null }),
        ]).toEqual(['under 4 KiB', '4–8 KiB', '16 KiB and up'])
    })

    it('says what changed before an approval, and why the resumes after ran', () => {
        expect(changesText({ edited: true, comments: 2, earlier: 1 })).toBe('edited, 2 comments, after 1 sent back')
        expect(changesText({ edited: false, comments: 0, earlier: 0 })).toBe('')
        expect(reasonsText({ ci: 1, review: 2 })).toBe('ci 1, review 2')
        expect(reasonsText({})).toBe('')
    })
})
