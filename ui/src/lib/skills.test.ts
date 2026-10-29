import { describe, expect, it } from 'vitest'

import type { Skill, SkillList } from '@/api/types'

import { skillQueryOf, skillsLine, skillsMatching } from './skills'

function skill(name: string, fields: Partial<Skill> = {}): Skill {
    return { name, description: null, source: 'canopy', path: 'x', body: '', ...fields }
}

describe('skillsLine', () => {
    it('counts the skills, and how many are the operator’s or the workspace’s', () => {
        const found: SkillList = {
            skills: [skill('a'), skill('b', { source: 'home' }), skill('c', { source: 'workspace' })],
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
