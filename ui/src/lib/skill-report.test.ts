import { describe, expect, it } from 'vitest'

import type { SkillsAgent, SkillsSkill, SkillsUse } from '@/api/types'

import {
    agentNote,
    agentUse,
    cellBar,
    cellText,
    cellTip,
    coverageText,
    loadRate,
    loadsTip,
    sentTip,
    shortAgent,
    skillsFigures,
    skillsLine,
    skillsSort,
    skillsWindow,
    sortedSkills,
    tokensChange,
    unaskedText,
} from './skill-report'

function used(by: string, counts: Partial<SkillsUse> = {}): SkillsUse {
    return {
        agent: by,
        offered: 4,
        loaded: 0,
        unoffered: 0,
        loads: 0,
        failed: 0,
        est_result_tokens: 0,
        front_matter_chars: 100,
        counted: 4,
        calls: 40,
        est_sent_tokens: 1_000,
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
        est_result_tokens: 2_000,
        front_matter_chars: 100,
        est_front_matter_tokens: 25,
        counted: 10,
        calls: 100,
        est_sent_tokens: 2_500,
        uses: [],
        ...counts,
    }
}

function agent(name: string, counts: Partial<SkillsAgent> = {}): SkillsAgent {
    return {
        agent: name,
        runs: 4,
        said: 4,
        unanswered: 0,
        unasked: 0,
        counted: 4,
        calls: 40,
        skills: 6,
        unused: 2,
        est_call_tokens: 300,
        est_sent_tokens: 12_000,
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
        expect(skillsSort({ order: 'rate' })).toBe('rate')
        expect(skillsSort({ order: 'loads' })).toBe('loads')
        expect(skillsSort({ order: 'cost' })).toBeUndefined()
        expect(skillsSort({ order: 'offered' })).toBeUndefined()
        expect(skillsSort({})).toBeUndefined()
    })

    it("says the window's state: the skills offered, those never loaded, and the front matter once counted", () => {
        const found = { days: 7, offered: 8, unused: 4, counted: 10, est_sent_tokens: 88_610 }
        expect(skillsLine(found)).toBe('8 skills offered over 7 days · 4 never loaded · ~88.6k tokens of front matter')
        expect(skillsLine({ ...found, offered: 1, unused: 0 })).toBe(
            '1 skill offered over 7 days · each one loaded · ~88.6k tokens of front matter',
        )
        // No run counted yet: the cost is left out, not said as nothing.
        expect(skillsLine({ ...found, counted: 0, est_sent_tokens: 0 })).toBe(
            '8 skills offered over 7 days · 4 never loaded',
        )
        expect(skillsLine({ ...found, days: 30, offered: 0, unused: 0 })).toBe('no skill offered over 30 days')
    })

    it('has no front matter figure while no run is counted for one, in the window or the one before', () => {
        const found = { offered: 8, unused: 4, loads: 24, counted: 10, est_sent_tokens: 88_610, est_call_tokens: 317 }
        expect(skillsFigures(found)).toEqual({ offered: 8, unused: 4, loads: 24, sent: 88_610, call: 317 })
        expect(skillsFigures({ ...found, counted: 0, est_sent_tokens: 0, est_call_tokens: null })).toEqual({
            offered: 8,
            unused: 4,
            loads: 24,
            sent: null,
            call: null,
        })
        expect(tokensChange(1_234.4)).toBe('1.2k')
    })

    it('opens on the most front matter sent, then the largest a call, a skill with none on record last', () => {
        const skills = [
            skill('alpha', { est_sent_tokens: 0, front_matter_chars: null, counted: 0 }),
            skill('bravo', { est_sent_tokens: 0, front_matter_chars: 400, counted: 0 }),
            skill('charlie', { est_sent_tokens: 9_000 }),
            skill('delta', { est_sent_tokens: 9_000, front_matter_chars: 900 }),
        ]
        expect(sortedSkills(skills).map((s) => s.name)).toEqual(['delta', 'charlie', 'bravo', 'alpha'])
        expect(sortedSkills(skills, 'name').map((s) => s.name)).toEqual(['alpha', 'bravo', 'charlie', 'delta'])
    })

    it('opens on the most runs offered while no size is on record, as in the first days it is kept', () => {
        const unsized = { est_sent_tokens: 0, front_matter_chars: null, counted: 0 }
        const skills = [
            skill('alpha', { ...unsized, offered: 2 }),
            skill('bravo', { ...unsized, offered: 19 }),
            skill('charlie', { ...unsized, offered: 19 }),
        ]
        expect(sortedSkills(skills).map((s) => s.name)).toEqual(['bravo', 'charlie', 'alpha'])
    })

    it('orders by the lowest load rate, the most runs offered first among equals, one never offered last', () => {
        const skills = [
            skill('often', { offered: 10, loaded: 9 }),
            skill('never-few', { offered: 3, loaded: 0 }),
            skill('never-many', { offered: 19, loaded: 0 }),
            skill('unasked', { offered: 0, loaded: 0 }),
        ]
        expect(sortedSkills(skills, 'rate').map((s) => s.name)).toEqual(['never-many', 'never-few', 'often', 'unasked'])
        expect(loadRate({ offered: 10, loaded: 9 })).toBe(0.9)
        expect(loadRate({ offered: 0, loaded: 0 })).toBeNull()
    })

    it('orders by the most loads, by name among equals', () => {
        const skills = [skill('b', { loads: 2 }), skill('a', { loads: 2 }), skill('c', { loads: 15 })]
        expect(sortedSkills(skills, 'loads').map((s) => s.name)).toEqual(['c', 'a', 'b'])
    })

    it('says what the front matter is counted over, and why the rest is left out', () => {
        expect(coverageText({ said: 21, counted: 10, unnamed: 0 })).toBe(
            'Front matter is counted over 10 of the 21 runs the runtime answered for: a run whose offer is from ' +
                "before canopy kept a description's length, or whose session is not read yet, is left out.",
        )
        expect(coverageText({ said: 1, counted: 1, unnamed: 2 })).toBe(
            'Front matter is counted over each of the 1 run the runtime answered for. 2 loads named no skill canopy ' +
                'could read, and count under none.',
        )
        expect(coverageText({ said: 0, counted: 0, unnamed: 1 })).toBe(
            'The runtime answered for no run, so no skill is counted as offered. 1 load named no skill canopy could ' +
                'read, and counts under none.',
        )
    })

    it('counts the runs no offer is on record for, apart, and says nothing when there are none', () => {
        expect(unaskedText([agent('a', { unasked: 5 }), agent('b', { unasked: 3, unanswered: 1 })])).toBe(
            "8 runs were never asked what they were offered: a task's, an epic's plan, or one from before canopy " +
                'asked. The runtime could not answer for 1 run. Their loads are counted all the same.',
        )
        expect(unaskedText([agent('a', { unasked: 1 })])).toBe(
            "1 run was never asked what it was offered: a task's, an epic's plan, or one from before canopy asked. " +
                'Their loads are counted all the same.',
        )
        expect(unaskedText([agent('a')])).toBe('')
    })

    it("heads a column with an agent's name less canopy's prefix, and leaves another's whole", () => {
        expect(shortAgent('canopy-worker-private')).toBe('worker-private')
        expect(shortAgent('canopy-chore-deps')).toBe('chore-deps')
        expect(shortAgent('my-own-agent')).toBe('my-own-agent')
        expect(shortAgent('canopy-')).toBe('canopy-')
    })

    it('reads a cell of the grid: loaded of offered, a dash where not offered, and a load with no offer', () => {
        const row = skill('audit', { uses: [used('canopy-worker', { loaded: 1 }), used('canopy-planner')] })
        expect(agentUse(row, 'canopy-worker')?.loaded).toBe(1)
        expect(agentUse(row, 'canopy-reviewer')).toBeUndefined()
        expect(cellText(agentUse(row, 'canopy-worker'))).toBe('1/4')
        expect(cellText(agentUse(row, 'canopy-planner'))).toBe('0/4')
        expect(cellText(undefined)).toBe('–')
        expect(cellText(used('a', { offered: 0, unoffered: 2 }))).toBe('2 loaded')
        // A call for it that failed, and nothing else: nothing was offered and nothing loaded.
        expect(cellText(used('a', { offered: 0, failed: 1 }))).toBe('–')
        expect(cellBar(agentUse(row, 'canopy-worker'))).toBe(25)
        expect(cellBar(agentUse(row, 'canopy-planner'))).toBe(0)
        // Not offered is a share of nothing: no bar, where never loaded is an empty one.
        expect(cellBar(undefined)).toBeNull()
        expect(cellBar(used('a', { offered: 0, unoffered: 2 }))).toBeNull()
    })

    it('says a cell in words on its tip, with what its front matter cost where that is counted', () => {
        expect(cellTip(used('canopy-reviewer', { offered: 5, loaded: 2, est_sent_tokens: 656 }))).toBe(
            'canopy-reviewer: offered in 5 runs, loaded in 2 · ~656 tokens of front matter sent',
        )
        expect(cellTip(used('canopy-planner', { offered: 5, counted: 0, est_sent_tokens: 0 }))).toBe(
            'canopy-planner: offered in 5 runs, loaded in none',
        )
        expect(cellTip(used('canopy-worker-private', { offered: 2, loaded: 2, unoffered: 2, counted: 0 }))).toBe(
            'canopy-worker-private: offered in 2 runs, loaded in 2 · loaded in 2 runs with no offer on record',
        )
        expect(cellTip(used('a', { offered: 0, unoffered: 1, counted: 0 }))).toBe(
            'a: loaded in 1 run with no offer on record',
        )
        expect(cellTip(undefined)).toBeUndefined()
        expect(cellTip(used('a', { offered: 0, failed: 1 }))).toBeUndefined()
    })

    it("says what a skill's loads and its front matter's cost hold besides the figure", () => {
        expect(loadsTip({ unoffered: 3, failed: 1 })).toBe('loaded in 3 runs with no offer on record · 1 call failed')
        expect(loadsTip({ unoffered: 0, failed: 2 })).toBe('2 calls failed')
        expect(loadsTip({ unoffered: 0, failed: 0 })).toBeUndefined()
        expect(sentTip({ offered: 11, counted: 6, calls: 234 })).toBe('over 6 of 11 runs offered it, 234 model calls')
        expect(sentTip({ offered: 3, counted: 0, calls: 0 })).toBe('counted over none of the 3 runs offered it')
        expect(sentTip({ offered: 0, counted: 0, calls: 0 })).toBeUndefined()
    })

    it("notes what an agent's figures leave out, and nothing for one counted whole", () => {
        expect(agentNote(agent('canopy-overseer', { skills: 0, unused: 0 }))).toBe('offered no skill')
        expect(agentNote(agent('canopy-worker-private', { said: 2, unasked: 5, counted: 1 }))).toBe(
            '5 never asked about · cost counted over 1 of 2',
        )
        expect(agentNote(agent('canopy-reviewer', { said: 5, unanswered: 1, counted: 3 }))).toBe(
            '1 not answered for · cost counted over 3 of 5',
        )
        // A run never asked about has no skills on record: that is not being offered none.
        expect(agentNote(agent('a', { said: 0, skills: 0, unasked: 3, counted: 0 }))).toBe('3 never asked about')
        expect(agentNote(agent('canopy-worker'))).toBe('')
    })
})
