import { describe, expect, it } from 'vitest'

import { planDecisions } from '@/lib/plan-decisions'
import type { PlanDecision } from '@/lib/plan-decisions'
import { parsePicks, PICKS_MAX, picksOn, withoutPicks, withPick } from '@/lib/plan-picks'
import type { PlanPicks } from '@/lib/plan-picks'

const PLAN = [
    '# Plan',
    '',
    '## Decisions',
    '',
    '### Decision 1: Which encoding the file is in',
    '',
    '- **A (chosen):** UTF-8, as the other exports are.',
    '- **B:** Latin-1, for the old spreadsheet.',
    '',
    '### Decision 2: Where the file is written',
    '',
    '- **A (chosen):** Beside the report.',
    '- **B:** In the exports folder.',
    '',
].join('\n')
const AT = '2026-10-08T12:00:00Z'

function decision(markdown: string, number: number): PlanDecision {
    const found = planDecisions(markdown).find((d) => d.number === number)
    if (found === undefined) {
        throw new Error(`no decision ${number}`)
    }
    return found
}

describe('picks', () => {
    it("holds a pick on its plan's decision, and none on another plan of the subject", () => {
        const all = withPick({}, 'ABC-1', 2, decision(PLAN, 1), 'B', AT)
        expect(picksOn(all['ABC-1'], 2, planDecisions(PLAN))).toEqual(new Map([[1, 'B']]))
        expect(picksOn(all['ABC-1'], 3, planDecisions(PLAN))).toEqual(new Map())
        expect(picksOn(undefined, 2, planDecisions(PLAN))).toEqual(new Map())
    })

    it('holds a pick while its decision reads as it did when picked, whatever the rest of the plan says', () => {
        const all = withPick({}, 'ABC-1', 2, decision(PLAN, 1), 'B', AT)
        const elsewhere = PLAN.replace('Beside the report.', 'Beside the report, as a sibling file.')
        expect(picksOn(all['ABC-1'], 2, planDecisions(elsewhere))).toEqual(new Map([[1, 'B']]))
        // Its own option reworded, or the planner's choice moved: the answer was not given to this question.
        const reworded = PLAN.replace('Latin-1, for the old spreadsheet.', 'UTF-16, for the old spreadsheet.')
        expect(picksOn(all['ABC-1'], 2, planDecisions(reworded))).toEqual(new Map())
        const moved = PLAN.replace('**A (chosen):** UTF-8', '**A:** UTF-8').replace(
            '**B:** Latin-1',
            '**B (chosen):** Latin-1',
        )
        expect(picksOn(all['ABC-1'], 2, planDecisions(moved))).toEqual(new Map())
    })

    it("drops a pick of the planner's own choice, and a subject left with none", () => {
        const first = decision(PLAN, 1)
        const picked = withPick({}, 'ABC-1', 2, first, 'B', AT)
        const both = withPick(picked, 'ABC-1', 2, decision(PLAN, 2), 'B', AT)
        expect(picksOn(both['ABC-1'], 2, planDecisions(PLAN))).toEqual(
            new Map([
                [1, 'B'],
                [2, 'B'],
            ]),
        )
        const back = withPick(both, 'ABC-1', 2, first, 'A', AT)
        expect(picksOn(back['ABC-1'], 2, planDecisions(PLAN))).toEqual(new Map([[2, 'B']]))
        expect(withPick(picked, 'ABC-1', 2, first, 'A', AT)).toEqual({})
    })

    it("starts a new plan with none of the last plan's picks", () => {
        const old = withPick({}, 'ABC-1', 2, decision(PLAN, 1), 'B', AT)
        const next = withPick(old, 'ABC-1', 3, decision(PLAN, 2), 'B', AT)
        expect(picksOn(next['ABC-1'], 3, planDecisions(PLAN))).toEqual(new Map([[2, 'B']]))
    })

    it("drops a subject's picks once they are sent, and leaves the others'", () => {
        const one = withPick({}, 'ABC-1', 2, decision(PLAN, 1), 'B', AT)
        const two = withPick(one, 'epic:2', 3, decision(PLAN, 1), 'B', AT)
        expect(Object.keys(withoutPicks(two, 'ABC-1'))).toEqual(['epic:2'])
    })

    it('keeps the subjects picked last, at most PICKS_MAX', () => {
        let all: PlanPicks = {}
        for (let i = 0; i <= PICKS_MAX; i += 1) {
            const at = new Date(Date.parse(AT) + i * 1000).toISOString()
            all = withPick(all, `ABC-${i}`, 1, decision(PLAN, 1), 'B', at)
        }
        expect(Object.keys(all)).toHaveLength(PICKS_MAX)
        expect(all['ABC-0']).toBeUndefined()
        expect(all[`ABC-${PICKS_MAX}`]).toBeDefined()
    })

    it('reads what is stored, dropping whatever is not a subject or a pick', () => {
        const stored = {
            'ABC-1': { plan: 2, at: AT, picks: { 1: { letter: 'B', digest: 'x' }, 2: { letter: 3 } } },
            'ABC-2': { plan: '2', at: AT, picks: {} },
            'ABC-3': { plan: 2, picks: {} },
        }
        expect(parsePicks(JSON.stringify(stored))).toEqual({
            'ABC-1': { plan: 2, at: AT, picks: { 1: { letter: 'B', digest: 'x' } } },
        })
        expect(parsePicks(null)).toEqual({})
        expect(parsePicks('[1]')).toEqual({})
        expect(parsePicks('{')).toEqual({})
    })
})
