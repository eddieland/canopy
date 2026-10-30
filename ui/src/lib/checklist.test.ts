import { describe, expect, it } from 'vitest'

import type { ChecklistItemCounts } from '@/api/types'

import { ANSWER_COLUMNS, checklistDays, checklistLine, itemsByRepo } from './checklist'

function item(repo: string, id: string, extra: Partial<ChecklistItemCounts> = {}): ChecklistItemCounts {
    return {
        repo,
        item: id,
        reminded: 3,
        passed: 3,
        fixed: 0,
        held: 0,
        not_applicable: 0,
        unanswered: 0,
        ...extra,
    }
}

// As the server sends them: by repository, each list in its order, which is not the ids' alphabetical one.
const ITEMS = [
    item('api', 'newspaper', { passed: 1, held: 2 }),
    item('api', 'doc-comments'),
    item('web', 'no-any', { reminded: 1, passed: 0, held: 1 }),
]

describe('checklistDays', () => {
    it('keeps a window the page offers, as a number or its digits, and drops the default and the rest', () => {
        expect(checklistDays(14)).toBe(14)
        expect(checklistDays('30')).toBe(30)
        expect(checklistDays('7')).toBeUndefined()
        expect(checklistDays(9)).toBeUndefined()
        expect(checklistDays('week')).toBeUndefined()
        expect(checklistDays(undefined)).toBeUndefined()
    })
})

describe('itemsByRepo', () => {
    it("groups the items by repository, keeping each list's order", () => {
        expect(itemsByRepo(ITEMS, undefined).map((g) => [g.repo, g.items.map((i) => i.item)])).toEqual([
            ['api', ['newspaper', 'doc-comments']],
            ['web', ['no-any']],
        ])
    })

    it("keeps only the repositories the filter chooses, and none when it chooses one with no list's answers", () => {
        expect(itemsByRepo(ITEMS, 'web').map((g) => g.repo)).toEqual(['web'])
        expect(itemsByRepo(ITEMS, 'api,web').map((g) => g.repo)).toEqual(['api', 'web'])
        expect(itemsByRepo(ITEMS, 'docs')).toEqual([])
    })
})

describe('checklistLine', () => {
    it('says the items, their repositories, the window, and the answers held', () => {
        expect(checklistLine(ITEMS, 7)).toBe('3 items in 2 repositories over 7 days · 3 held')
        expect(checklistLine(ITEMS.slice(0, 1), 1)).toBe('1 item in 1 repository over 1 day · 2 held')
    })

    it('says no list was answered over a window with none', () => {
        expect(checklistLine([], 14)).toBe('no checklist answered over 14 days')
    })
})

describe('ANSWER_COLUMNS', () => {
    it("names the answers in canopy checklist's words and order", () => {
        expect(ANSWER_COLUMNS.map((c) => c.label)).toEqual(['pass', 'fixed', 'held', 'n/a', 'unanswered'])
    })
})
