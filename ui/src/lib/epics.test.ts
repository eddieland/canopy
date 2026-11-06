import { describe, expect, it } from 'vitest'

import { mockEpicDetails, mockEpics } from '@/api/mocks'
import type { EpicMember } from '@/api/types'

import { EPIC_LOOK, breakdownFull, citedBy, cites, entriesFiled, epicId, epicTitle, unplaced } from './epics'

describe('EPIC_LOOK', () => {
    it('colors each standing as the run state it means: a proposed plan waits on you, one with none is stuck', () => {
        expect(Object.fromEntries(Object.entries(EPIC_LOOK).map(([standing, look]) => [standing, look.state]))).toEqual(
            {
                queued: 'stopped',
                planning: 'running',
                proposed: 'blocked',
                approved: 'done',
                unplanned: 'failed',
                stopped: 'stopped',
            },
        )
        expect(EPIC_LOOK.proposed.word).toBe('waiting on you')
        // A queued and a stopped epic wear the same muted color, so their words tell them apart.
        expect(EPIC_LOOK.queued.word).not.toBe(EPIC_LOOK.stopped.word)
    })
})

describe('epicTitle', () => {
    it("names an epic by its goal's first line that holds anything", () => {
        expect(epicTitle('\n  Move billing to v2.  \n\nThen retire v1.')).toBe('Move billing to v2.')
        expect(epicTitle('   ')).toBe('   ')
    })
})

describe('breakdownFull', () => {
    it('reads full only once every entry of a breakdown has a member', () => {
        expect(mockEpics.map((epic) => breakdownFull(epic))).toEqual([false, false, false, false])
        expect(breakdownFull({ entries: 4, entries_with_members: 4 })).toBe(true)
        expect(breakdownFull({ entries: 4, entries_with_members: 3 })).toBe(false)
        // No breakdown, or one with no entries, has nothing to fill.
        expect(breakdownFull({ entries: null, entries_with_members: 0 })).toBe(false)
        expect(breakdownFull({ entries: 0, entries_with_members: 0 })).toBe(false)
    })
})

describe('entriesFiled', () => {
    it("counts the breakdown's entries with a member, and nothing before there is a breakdown", () => {
        expect(mockEpics.map((epic) => entriesFiled(epic))).toEqual([
            'no breakdown',
            'no breakdown',
            '0 of 3 entries filed',
            '2 of 4 entries filed',
        ])
        expect(entriesFiled({ entries: 1, entries_with_members: 1, standing: 'approved' })).toBe('1 of 1 entry filed')
    })

    it('tells a plan whose breakdown cannot be read from no plan at all', () => {
        expect(entriesFiled({ entries: null, entries_with_members: 0, standing: 'proposed' })).toBe(
            'breakdown unreadable',
        )
        expect(entriesFiled({ entries: null, entries_with_members: 0, standing: 'approved' })).toBe(
            'breakdown unreadable',
        )
        expect(entriesFiled({ entries: null, entries_with_members: 0, standing: 'unplanned' })).toBe('no breakdown')
    })
})

/** The approved mock epic's breakdown: B1 to B4. */
const billing = mockEpicDetails[0]?.outline?.entries ?? []

describe('epicId', () => {
    it('reads a whole number, and nothing else, as an epic', () => {
        expect(epicId('9007199254740991')).toBe(Number.MAX_SAFE_INTEGER)
        // One past it would read as another epic's id.
        expect(epicId('9007199254740993')).toBeUndefined()
        expect(['1', '42', '0', '01', '1.5', 'abc', '', '-1'].map((text) => epicId(text))).toEqual([
            1,
            42,
            undefined,
            undefined,
            undefined,
            undefined,
            undefined,
            undefined,
        ])
    })
})

/** The approved mock epic's entries that cite `id`. */
function citing(id: string): string[] {
    return billing.filter((entry) => cites(entry, id)).map((entry) => entry.id)
}

describe('cites', () => {
    it('finds the entries that cover a requirement, provide or use a contract, or are or follow an entry', () => {
        expect(citing('R1')).toEqual(['B1', 'B3'])
        expect(citing('C1')).toEqual(['B1', 'B2', 'B3'])
        expect(citing('B1')).toEqual(['B1', 'B2', 'B3', 'B4'])
        expect(citing('B4')).toEqual(['B4'])
        expect(citing('R9')).toEqual([])
    })
})

describe('citedBy', () => {
    it('says who cites an id, read the other way from the board, and when none does', () => {
        expect(citedBy(billing, 'R1')).toBe('covered by B1, B3')
        expect(citedBy(billing, 'R9')).toBe('covered by no entry')
        expect(citedBy(billing, 'C1')).toBe('provided by B1 · used by B2, B3')
        expect(citedBy(billing, 'B3')).toBe('B4 comes after it')
        expect(citedBy(billing, 'B1')).toBe('B2, B3, B4 come after it')
        expect(citedBy(billing, 'B4')).toBe('nothing comes after it')
    })
})

/** A member registered against `entries`, of which `dropped` the approved plan dropped. */
function member(key: string, entries: string[], dropped: string[] = []): EpicMember {
    return {
        key,
        title: null,
        entries,
        dropped,
        added_at: '2026-10-08T07:10:00Z',
        added_channel: 'cli',
        phase: null,
        prs: [],
        latest_run: null,
    }
}

describe('unplaced', () => {
    it('lists the members of no entry, and those with an entry dropped whatever else they fulfil', () => {
        const found = unplaced([
            member('ABC-1', ['B1']),
            member('ABC-2', []),
            member('ABC-3', [], ['B5']),
            member('ABC-4', ['B2'], ['B6']),
        ])
        expect(found.none.map((m) => m.key)).toEqual(['ABC-2'])
        expect(found.dropped.map((m) => m.key)).toEqual(['ABC-3', 'ABC-4'])
        expect(found.registered).toEqual([])
    })

    it('lists the members registered against entries while the board has no rows to show them on', () => {
        const found = unplaced([member('ABC-1', ['B1']), member('ABC-2', [])], false)
        expect(found.registered.map((m) => m.key)).toEqual(['ABC-1'])
        expect(found.none.map((m) => m.key)).toEqual(['ABC-2'])
    })
})
