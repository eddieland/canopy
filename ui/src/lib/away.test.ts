import { describe, expect, it } from 'vitest'

import { mockAttention } from '@/api/mocks'
import type { AttentionItem } from '@/api/types'

import { awayChanges, awayLine } from './away'

const asked = mockAttention[0] as AttentionItem
const parked: AttentionItem = { ...asked, id: 'a2', reason: 'needs_reviewer' }
const finding: AttentionItem = { ...asked, id: 'a3', reason: 'deps-1', finding: true }
const none = { needsYou: 0, cleared: 0, prsOpened: 0, runsEnded: 0 }

describe('awayChanges', () => {
    it('counts as needing you only the new items that block work, and as cleared those gone from the list', () => {
        const changes = awayChanges(['gone-1', 'gone-2', 'a2'], [asked, parked, finding], { ended: 4, prs_opened: 2 })
        expect(changes).toEqual({ needsYou: 1, cleared: 2, prsOpened: 2, runsEnded: 4 })
    })

    it('counts nothing for an item that was listed before and still is', () => {
        expect(awayChanges(['a1'], [asked], { ended: 0, prs_opened: 0 })).toEqual(none)
    })
})

describe('awayLine', () => {
    const since = '2026-10-08T14:05:00Z'
    const now = '2026-10-08T15:30:00Z'

    it('says what needs you first, then what cleared, the PRs, and the runs, from when the tab was hidden', () => {
        const line = awayLine(since, now, { needsYou: 1, cleared: 3, prsOpened: 2, runsEnded: 1 })
        expect(line).toMatch(/^Since \d\d:\d\d: 1 new item needs you, 3 items cleared, 2 PRs opened, 1 run ended$/u)
    })

    it('leaves out every count of none, and agrees in number', () => {
        expect(awayLine(since, now, { ...none, needsYou: 2 })).toMatch(/: 2 new items need you$/u)
        expect(awayLine(since, now, { ...none, cleared: 1, prsOpened: 1 })).toMatch(/: 1 item cleared, 1 PR opened$/u)
    })

    it('says nothing when nothing changed', () => {
        expect(awayLine(since, now, none)).toBeNull()
    })

    it('names the day as well when the tab was hidden on another', () => {
        expect(awayLine('2026-10-06T14:05:00Z', now, { ...none, runsEnded: 2 })).toMatch(/^Since Oct \d+ \d\d:\d\d: /u)
    })
})
