import { describe, expect, it } from 'vitest'

import type { Skill, SkillList } from '@/api/types'

import { agentName, offeredLine, skillQueryOf, skillsLine, skillsMatching } from './skills'

function skill(name: string, fields: Partial<Skill> = {}): Skill {
    return { name, description: null, source: 'canopy', path: 'x', offered: [], denied: [], body: '', ...fields }
}

describe('agentName', () => {
    it("drops the prefix every one of canopy's agents carries, and nothing else", () => {
        expect(agentName('canopy-worker-private')).toBe('worker-private')
        expect(agentName('my-canopy-agent')).toBe('my-canopy-agent')
    })
})

describe('offeredLine', () => {
    it('says every agent when none is denied, and names both sides when some are', () => {
        expect(offeredLine(skill('a', { offered: ['canopy-worker', 'canopy-chore'] }))).toBe('offered to every agent')
        expect(offeredLine(skill('a', { offered: ['canopy-worker'], denied: ['canopy-overseer'] }))).toBe(
            'offered to worker; denied to overseer',
        )
        expect(offeredLine(skill('a', { denied: ['canopy-overseer', 'canopy-chore'] }))).toBe(
            'offered to no agent: denied to overseer, chore',
        )
        // Every agent's rules unread: the page says why above the list.
        expect(offeredLine(skill('a'))).toBe('no agent asked')
    })
})

describe('skillsLine', () => {
    it('counts the skills, and how many are the operator’s or the workspace’s', () => {
        const found: SkillList = {
            skills: [skill('a'), skill('b', { source: 'home' }), skill('c', { source: 'workspace' })],
            unread: [],
            error: null,
        }
        expect(skillsLine(found)).toBe('3 skills, 2 of them yours')
        expect(skillsLine({ ...found, skills: [skill('a')] })).toBe("1 skill, all canopy's or the runtime's")
        expect(skillsLine({ ...found, skills: [] })).toBe('no skills found')
    })
})

describe('skillsMatching', () => {
    it('keeps the skills whose name or description holds the text, in any case', () => {
        const skills = [skill('tracker-jira'), skill('terse', { description: 'Say less.' }), skill('release-notes')]
        expect(skillsMatching(skills, 'JIRA').map((s) => s.name)).toEqual(['tracker-jira'])
        expect(skillsMatching(skills, 'say').map((s) => s.name)).toEqual(['terse'])
        expect(skillsMatching(skills, undefined)).toHaveLength(3)
    })
})

describe('skillQueryOf', () => {
    it('keeps a string with a word in it, cut to its limit', () => {
        expect(skillQueryOf('jira')).toBe('jira')
        expect(skillQueryOf('   ')).toBeUndefined()
        expect(skillQueryOf(3)).toBeUndefined()
        expect(skillQueryOf('x'.repeat(300))).toHaveLength(100)
    })
})
