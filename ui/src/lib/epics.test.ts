import { describe, expect, it } from 'vitest'

import { mockEpics } from '@/api/mocks'

import { EPIC_LOOK, entriesFiled, epicTitle } from './epics'

describe('EPIC_LOOK', () => {
    it('colors each standing as the run state it means: a proposed plan waits on you, one with none is stuck', () => {
        expect(Object.fromEntries(Object.entries(EPIC_LOOK).map(([standing, look]) => [standing, look.state]))).toEqual(
            {
                queued: 'stopped',
                planning: 'running',
                proposed: 'blocked',
                approved: 'done',
                unplanned: 'failed',
            },
        )
        expect(EPIC_LOOK.proposed.word).toBe('waiting on you')
    })
})

describe('epicTitle', () => {
    it("names an epic by its goal's first line that holds anything", () => {
        expect(epicTitle('\n  Move billing to v2.  \n\nThen retire v1.')).toBe('Move billing to v2.')
        expect(epicTitle('   ')).toBe('   ')
    })
})

describe('entriesFiled', () => {
    it("counts the breakdown's entries with a member, and nothing before there is a breakdown", () => {
        expect(mockEpics.map((epic) => entriesFiled(epic))).toEqual([
            null,
            '0 of 3 entries filed',
            '2 of 4 entries filed',
        ])
        expect(entriesFiled({ entries: 1, entries_with_members: 1 })).toBe('1 of 1 entry filed')
    })
})
