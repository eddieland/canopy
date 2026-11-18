import { describe, expect, it } from 'vitest'

import type { SkillsAgent, SkillsSkill, SkillsUse } from '@/api/types'

import {
    agentCallTip,
    agentLoadsTip,
    coverageText,
    frontMatterTip,
    loadRate,
    loadsTip,
    noOffer,
    noOfferTip,
    offersText,
    pickedAgent,
    rateText,
    rateTip,
    skillRows,
    skillsAgent,
    skillsFigures,
    skillsLine,
    skillsSort,
    skillsWindow,
    sortedAgents,
    sortedRows,
    tokensChange,
} from './skill-report'

function used(by: string, counts: Partial<SkillsUse> = {}): SkillsUse {
    return {
        agent: by,
        offered: 4,
        loaded: 0,
        unoffered: 0,
        loads: 0,
        failed: 0,
        est_body_tokens: 0,
        front_matter_chars: 100,
        est_call_tokens: 25,
        counted: 4,
        calls: 40,
        est_front_matter_tokens: 1_000,
        ...counts,
    }
}

function skill(name: string, counts: Partial<SkillsSkill> = {}): SkillsSkill {
    return {
        name,
        countable: true,
        unused: false,
        offered: 10,
        loaded: 5,
        unoffered: 0,
        loads: 5,
        failed: 0,
        est_body_tokens: 2_000,
        front_matter_chars: 100,
        est_call_tokens: 25,
        counted: 10,
        calls: 100,
        est_front_matter_tokens: 2_500,
        uses: [],
        ...counts,
    }
}

function agent(name: string, counts: Partial<SkillsAgent> = {}): SkillsAgent {
    return {
        agent: name,
        runs: 4,
        unanswered: 0,
        unasked: 0,
        listed: 4,
        unsized: 0,
        unread: 0,
        counted: 4,
        calls: 40,
        skills: 6,
        unused: 2,
        loads: 3,
        unnamed: 0,
        est_call_tokens: 300,
        est_front_matter_tokens: 12_000,
        ...counts,
    }
}

describe('the Skills report', () => {
    it('offers the week and 30 days, as the health page does', () => {
        expect(skillsWindow({ days: '30' })).toEqual({ days: 30 })
        expect(skillsWindow({ days: 7 })).toEqual({ days: 7 })
        expect(skillsWindow({ days: '14' })).toBeUndefined()
        expect(skillsWindow({})).toBeUndefined()
    })

    it('keeps an order it offers, and spells the one it opens on as none', () => {
        expect(skillsSort({ order: 'least' })).toBe('least')
        expect(skillsSort({ order: 'most' })).toBe('most')
        expect(skillsSort({ order: 'cost' })).toBeUndefined()
        expect(skillsSort({ order: 'name' })).toBeUndefined()
        expect(skillsSort({})).toBeUndefined()
    })

    it("keeps any agent's name from the search, and holds it to the agents the window has", () => {
        expect(skillsAgent({ agent: 'canopy-reviewer' })).toBe('canopy-reviewer')
        expect(skillsAgent({ agent: '' })).toBeUndefined()
        expect(skillsAgent({ agent: 7 })).toBeUndefined()
        const agents = [agent('canopy-worker'), agent('canopy-reviewer')]
        expect(pickedAgent(agents, 'canopy-reviewer')?.agent).toBe('canopy-reviewer')
        // An agent the window does not have reads as every agent.
        expect(pickedAgent(agents, 'canopy-planner')).toBeUndefined()
        expect(pickedAgent(agents, undefined)).toBeUndefined()
    })

    it("says the window's state: the skills offered, those never loaded, and the front matter with its cover", () => {
        const found = {
            days: 7,
            offered: 8,
            unused: 4,
            loads: 24,
            listed: 19,
            counted: 8,
            est_call_tokens: 348,
            skills: [],
        }
        expect(skillsLine(found)).toBe(
            '8 skills offered over 7 days · 4 never loaded · ' +
                'front matter ~348 tokens a call in 8 of 19 runs offered a skill',
        )
        // Counted whole, the cost needs no cover beside it.
        expect(skillsLine({ ...found, offered: 1, unused: 0, counted: 19 })).toBe(
            '1 skill offered over 7 days · each one loaded · front matter ~348 tokens a call',
        )
        // A skill the runtime cannot name has loads nothing counts: not known loaded.
        expect(
            skillsLine({
                ...found,
                offered: 1,
                unused: 0,
                skills: [{ countable: false, offered: 2 }] as SkillsSkill[],
            }),
        ).toContain('1 skill offered over 7 days · none known never loaded')
        // No run counted yet: not known, which is not a cost of nothing.
        expect(skillsLine({ ...found, counted: 0, est_call_tokens: null })).toBe(
            '8 skills offered over 7 days · 4 never loaded · front matter not counted yet',
        )
        expect(skillsLine({ ...found, days: 30, offered: 0, unused: 0, loads: 0 })).toBe(
            'no skill offered over 30 days',
        )
        // Loaded by runs nothing says what they were offered.
        expect(skillsLine({ ...found, offered: 0, unused: 0, loads: 12 })).toBe(
            'no skill offered over 7 days · 12 loads',
        )
    })

    it('compares a window with the one before by its counts and the mean of a call', () => {
        expect(skillsFigures({ offered: 8, unused: 4, est_call_tokens: 348 })).toEqual({
            offered: 8,
            unused: 4,
            call: 348,
        })
        expect(skillsFigures({ offered: 4, unused: 3, est_call_tokens: null }).call).toBeNull()
        expect(tokensChange(1_234.4)).toBe('1.2k')
    })

    it('lists each skill over every agent, or the skills one agent was offered or loaded, by its own runs', () => {
        const skills = [
            skill('audit', {
                uses: [used('canopy-worker', { loaded: 2, loads: 2 }), used('canopy-reviewer', { offered: 3 })],
            }),
            skill('terse', { uses: [used('canopy-worker')] }),
            skill('My_Skill', { countable: false, uses: [used('canopy-reviewer')] }),
        ]
        expect(skillRows(skills, undefined).map((r) => r.name)).toEqual(['audit', 'terse', 'My_Skill'])
        const reviewer = skillRows(skills, 'canopy-reviewer')
        expect(reviewer.map((r) => [r.name, r.offered, r.unused])).toEqual([
            // Loaded by the worker, never by the reviewer: unused for this agent, whatever another did.
            ['audit', 3, true],
            // A load of it is counted under no name, so it cannot be said never to load.
            ['My_Skill', 4, false],
        ])
        expect(skillRows(skills, 'canopy-worker').map((r) => [r.name, r.unused])).toEqual([
            ['audit', false],
            ['terse', true],
        ])
    })

    it('opens on the most front matter, then the largest a call, a skill with none on record last', () => {
        const rows = [
            skill('alpha', { est_front_matter_tokens: null, front_matter_chars: null, counted: 0 }),
            skill('bravo', { est_front_matter_tokens: null, front_matter_chars: 400, counted: 0 }),
            skill('charlie', { est_front_matter_tokens: 9_000 }),
            skill('delta', { est_front_matter_tokens: 9_000, front_matter_chars: 900 }),
            skill('echo', { est_front_matter_tokens: 0 }),
        ]
        // A cost of nothing is known, and sorts before one that is not.
        expect(sortedRows(rows).map((r) => r.name)).toEqual(['delta', 'charlie', 'echo', 'bravo', 'alpha'])
    })

    it('opens on the most runs offered while no size is on record, as in the first days it is kept', () => {
        const unsized = { est_front_matter_tokens: null, front_matter_chars: null, counted: 0 }
        const rows = [
            skill('alpha', { ...unsized, offered: 2 }),
            skill('bravo', { ...unsized, offered: 19 }),
            skill('charlie', { ...unsized, offered: 19 }),
        ]
        expect(sortedRows(rows).map((r) => r.name)).toEqual(['bravo', 'charlie', 'alpha'])
    })

    it('orders the least loaded by those never loaded, the costliest first, then the lowest rate', () => {
        const rows = [
            skill('often', { offered: 10, loaded: 9 }),
            skill('rarely', { offered: 10, loaded: 1 }),
            skill('never-cheap', { unused: true, offered: 19, loaded: 0, loads: 0, est_front_matter_tokens: 300 }),
            skill('never-dear', { unused: true, offered: 3, loaded: 0, loads: 0, est_front_matter_tokens: 9_000 }),
            // No run offered it loaded it, and a run with no offer on record did: not a skill to deny.
            skill('elsewhere', { offered: 5, loaded: 0, loads: 2, unoffered: 2 }),
            skill('unasked', { offered: 0, loaded: 0 }),
            skill('Odd_Name', { countable: false, offered: 10, loaded: 0 }),
        ]
        expect(sortedRows(rows, 'least').map((r) => r.name)).toEqual([
            'never-dear',
            'never-cheap',
            'elsewhere',
            'rarely',
            'often',
            'Odd_Name',
            'unasked',
        ])
    })

    it('orders the most loaded by the highest rate, the most runs offered among equals, no rate last', () => {
        const rows = [
            skill('half', { offered: 10, loaded: 5 }),
            skill('all-few', { offered: 2, loaded: 2 }),
            skill('all-many', { offered: 19, loaded: 19 }),
            skill('unasked', { offered: 0, loaded: 0 }),
        ]
        expect(sortedRows(rows, 'most').map((r) => r.name)).toEqual(['all-many', 'all-few', 'half', 'unasked'])
    })

    it('says never for a skill no run loaded, where a muted zero would bury it, and a dash for no rate', () => {
        expect(loadRate({ countable: true, offered: 10, loaded: 9 })).toBe(0.9)
        expect(loadRate({ countable: true, offered: 0, loaded: 0 })).toBeNull()
        expect(loadRate({ countable: false, offered: 10, loaded: 0 })).toBeNull()
        expect(rateText({ countable: true, unused: false, offered: 19, loaded: 12 })).toBe('63%')
        expect(rateText({ countable: true, unused: true, offered: 19, loaded: 0 })).toBe('never')
        // Loaded by a run with no offer on record: no run offered it loaded it, which is not never.
        expect(rateText({ countable: true, unused: false, offered: 5, loaded: 0 })).toBe('0%')
        expect(rateText({ countable: true, unused: false, offered: 286, loaded: 1 })).toBe('<1%')
        expect(rateText({ countable: true, unused: false, offered: 0, loaded: 0 })).toBe('–')
        expect(rateText({ countable: false, unused: false, offered: 10, loaded: 0 })).toBe('–')
    })

    it('says what a rate counts on its tip, and why a row has none', () => {
        expect(rateTip({ countable: true, offered: 19, loaded: 12, unoffered: 3 })).toBe(
            'loaded in 12 of the 19 runs offered it · loaded in 3 runs with no offer on record',
        )
        expect(rateTip({ countable: true, offered: 1, loaded: 0, unoffered: 0 })).toBe(
            'loaded in 0 of the 1 run offered it',
        )
        expect(rateTip({ countable: true, offered: 0, loaded: 0, unoffered: 2 })).toBe(
            'no offer on record names it · loaded in 2 runs with no offer on record',
        )
        expect(rateTip({ countable: false, offered: 4, loaded: 0, unoffered: 0 })).toContain(
            'its loads are among those that named no skill',
        )
    })

    it("gives a cost's parts on its tip, never as a product, and says when none is counted", () => {
        expect(frontMatterTip({ offered: 11, counted: 6, calls: 234 })).toBe(
            'over 234 model calls, in 6 of 11 runs offered it',
        )
        expect(frontMatterTip({ offered: 3, counted: 0, calls: 0 })).toBe(
            'none of the 3 runs offered it is counted: no length on record, or no model calls on record',
        )
        expect(frontMatterTip({ offered: 0, counted: 0, calls: 0 })).toBeUndefined()
        expect(loadsTip({ unoffered: 3 })).toBe('3 of the runs that loaded it have no offer on record')
        expect(loadsTip({ unoffered: 1 })).toBe('1 of the runs that loaded it has no offer on record')
        expect(loadsTip({ unoffered: 0 })).toBeUndefined()
    })

    it('says what the front matter is counted over, split by why the rest is left out, on every visit', () => {
        expect(coverageText({ listed: 19, unsized: 5, unread: 6, counted: 8, unnamed: 0 })).toBe(
            'Front matter is counted over 8 of the 19 runs offered a skill: 5 from before canopy kept a ' +
                "skill's length, 6 with no model calls on record.",
        )
        expect(coverageText({ listed: 1, unsized: 0, unread: 0, counted: 1, unnamed: 2 })).toBe(
            'Front matter is counted over each of the 1 run offered a skill. 2 loads named no skill canopy could ' +
                'read: any skill here may be among them.',
        )
        expect(coverageText({ listed: 0, unsized: 0, unread: 0, counted: 0, unnamed: 1 })).toBe(
            'No run was offered a skill on record, so no front matter is counted. 1 load named no skill canopy ' +
                'could read: any skill here may be the one it loaded.',
        )
    })

    it('counts the runs with no offer on record apart, by why, and says so when every run has one', () => {
        expect(offersText({ runs: 30, unanswered: 1, unasked: 8 })).toBe(
            'No offer on record for 9 of 30 runs: the runtime could not answer for 1, and canopy never asked ' +
                "about 8, a task's, an epic's plan, or one from before it asked. They count under the agent canopy " +
                'ships for their kind of run, and their loads are counted.',
        )
        expect(offersText({ runs: 4, unanswered: 2, unasked: 0 })).toBe(
            'No offer on record for 2 of 4 runs: the runtime could not answer for 2. They count under the agent ' +
                'canopy ships for their kind of run, and their loads are counted.',
        )
        expect(offersText({ runs: 21, unanswered: 0, unasked: 0 })).toBe('Each of the 21 runs has its offer on record.')
        expect(offersText({ runs: 0, unanswered: 0, unasked: 0 })).toBe('')
    })

    it('lists the agents by the heaviest list a call, then those not counted, offered none, and unknown', () => {
        const agents = [
            agent('canopy-overseer', {
                skills: 0,
                unused: 0,
                listed: 0,
                est_call_tokens: 0,
                est_front_matter_tokens: 0,
            }),
            agent('canopy-worker', { est_call_tokens: 387 }),
            agent('canopy-worker-private', { skills: null, unused: null, est_call_tokens: null }),
            agent('canopy-planner', { counted: 0, est_call_tokens: null, est_front_matter_tokens: null }),
            agent('canopy-reviewer', { est_call_tokens: 900 }),
            agent('canopy-chore', { est_call_tokens: 387 }),
        ]
        expect(sortedAgents(agents).map((a) => a.agent)).toEqual([
            'canopy-reviewer',
            // Equal lists keep the server's order.
            'canopy-worker',
            'canopy-chore',
            'canopy-planner',
            'canopy-overseer',
            'canopy-worker-private',
        ])
    })

    it("splits an agent's runs with no offer on record by why, on the figure's tip", () => {
        expect(noOffer({ unasked: 5, unanswered: 1 })).toBe(6)
        expect(noOfferTip({ unasked: 5, unanswered: 1 })).toBe(
            'canopy never asked about 5 · the runtime could not answer for 1',
        )
        expect(noOfferTip({ unasked: 0, unanswered: 2 })).toBe('the runtime could not answer for 2')
        expect(noOfferTip({ unasked: 0, unanswered: 0 })).toBeUndefined()
    })

    it("says what an agent's cost of a call is a mean over, or why it has none", () => {
        const counted = { skills: 7, listed: 4, unsized: 0, unread: 2, counted: 2, calls: 128 }
        expect(agentCallTip(counted)).toBe('over 128 model calls, in 2 of 4 runs offered a skill')
        expect(agentCallTip({ ...counted, counted: 0, calls: 0, unsized: 1, unread: 3 })).toBe(
            "none of its 4 runs offered a skill is counted: 1 from before canopy kept a skill's length, 3 " +
                'with no model calls on record',
        )
        // Known to carry none, which is a zero, against nothing known, which is a dash.
        expect(agentCallTip({ ...counted, skills: 0, listed: 0 })).toBe('offered no skill, so its calls carry none')
        expect(agentCallTip({ ...counted, skills: null, listed: 0 })).toBe('no offer on record for any of its runs')
        expect(agentLoadsTip({ unnamed: 1 })).toBe('and 1 load that named no skill: any skill of its may be among them')
        expect(agentLoadsTip({ unnamed: 0 })).toBeUndefined()
    })
})
