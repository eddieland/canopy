import { describe, expect, it } from 'vitest'

import { mockEpicPlans } from '@/api/mocks'
import type { EpicPlans, PlanSummary, TicketPlans } from '@/api/types'
import { approveLabel, epicOpenDecisions, openDecisions } from '@/lib/plan-state'

const DECIDING = [
    '# Plan',
    '',
    '## Decisions',
    '',
    '### Decision 1: Which encoding the file is in',
    '',
    '- **A (chosen):** UTF-8, as the other exports are.',
    '- **B:** Latin-1, for the old spreadsheet.',
    '',
].join('\n')

const PLAN: PlanSummary = {
    id: 2,
    run_id: 41,
    status: 'proposed',
    created_at: '2026-10-08T11:00:00Z',
    approved_at: null,
    approved_channel: null,
    approved_reason: null,
    effort: null,
    epic_plan: null,
}

function plans(fields: Partial<TicketPlans> = {}, plan: PlanSummary = PLAN, text: string | null = DECIDING) {
    const found: TicketPlans = {
        needed: true,
        setting: null,
        trivial: null,
        policy: 'approve',
        planning: null,
        changes_asked: null,
        plans: [plan],
        newest: {
            plan,
            path: '/state/plans/ABC-1/41.md',
            file_name: '41-PROPOSED.md',
            text,
            problem: null,
            sha256: 'abc',
            edited: false,
            changed_since_approval: false,
            ticket_changed: [],
            persona: null,
        },
        threads: [],
        ...fields,
    }
    return found
}

// Epic 2's mock plans, its waiting plan reading `text`, with `fields` over them.
function epicPlans(text: string, fields: Partial<EpicPlans> = {}): EpicPlans {
    const found = mockEpicPlans.find((epic) => epic.epic_id === 2)
    const newest = found?.plans.at(-1)
    if (found === undefined || newest === undefined) {
        throw new Error('no mock plans of epic:2')
    }
    return { ...found, plans: [...found.plans.slice(0, -1), { ...newest, text }], ...fields }
}

describe('openDecisions', () => {
    it('finds the decisions of a plan proposed, as its file reads', () => {
        expect(openDecisions(plans()).map((decision) => decision.question)).toEqual(['Which encoding the file is in'])
    })

    it('finds none of a plan that waits on no answer, or whose file does not read', () => {
        expect(openDecisions(plans({ planning: 7 }))).toEqual([])
        expect(openDecisions(plans({}, { ...PLAN, status: 'approved' }))).toEqual([])
        expect(openDecisions(plans({}, { ...PLAN, status: 'superseded' }))).toEqual([])
        expect(openDecisions(plans({}, PLAN, null))).toEqual([])
        expect(openDecisions(plans({ newest: null, plans: [] }))).toEqual([])
    })

    it("finds an epic's the same way: its newest plan's, while it is proposed and no plan run works", () => {
        expect(epicOpenDecisions(epicPlans(DECIDING))).toHaveLength(1)
        expect(epicOpenDecisions(epicPlans(DECIDING, { planning: 5 }))).toEqual([])
        expect(epicOpenDecisions(epicPlans('# Plan\n'))).toEqual([])
        expect(epicOpenDecisions(epicPlans(DECIDING, { plans: [] }))).toEqual([])
    })
})

describe('approveLabel', () => {
    it('says what an approval takes: notes, or the planner’s choices, or the plan alone', () => {
        expect(approveLabel({})).toBe('Approve')
        expect(approveLabel({ planned: true })).toBe('Approve as planned')
        expect(approveLabel({ noted: true })).toBe('Approve with notes')
        // An answer is a note: the choices it leaves the planner's go unnamed beside it.
        expect(approveLabel({ noted: true, planned: true })).toBe('Approve with notes')
    })

    it('leads with the save an edit not yet saved needs first', () => {
        expect(approveLabel({ saves: true })).toBe('Save and approve')
        expect(approveLabel({ saves: true, planned: true })).toBe('Save and approve as planned')
        expect(approveLabel({ saves: true, noted: true })).toBe('Save and approve with notes')
    })
})
