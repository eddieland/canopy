import { describe, expect, it } from 'vitest'

import type { ChecklistAnswer, ChecklistItemCounts, ChecklistWeek } from '@/api/types'

import {
    ANSWER_COLUMNS,
    answersByRepo,
    answersByWeek,
    answersLine,
    answersWords,
    checklistDays,
    checklistFigures,
    checklistLine,
    checklistSort,
    checklistVerdict,
    itemKey,
    itemsByRepo,
    pickedItem,
    sortGroups,
    weekBars,
} from './checklist'

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
        held_runs: [],
        fixed_runs: [],
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
        expect(checklistDays(7)).toBe(7)
        expect(checklistDays('30')).toBe(30)
        expect(checklistDays('14')).toBeUndefined()
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

function answer(repo: string, id: string, said: ChecklistAnswer['answer'], reason: string | null = null) {
    return { repo, item: id, answer: said, reason }
}

// A joint run's answers, as the server sends them: by repository, each list in its order.
const ANSWERS: ChecklistAnswer[] = [
    answer('api', 'newspaper', 'held', 'The module keeps its order.'),
    answer('api', 'doc-comments', 'pass'),
    answer('api', 'general-types', 'pass'),
    answer('web', 'no-any', 'fixed'),
    answer('web', 'query-keys', 'unanswered'),
]

describe('answersByRepo', () => {
    it("groups a run's answers by repository, keeping each list's order", () => {
        expect(answersByRepo(ANSWERS).map((g) => [g.repo, g.answers.map((a) => a.item)])).toEqual([
            ['api', ['newspaper', 'doc-comments', 'general-types']],
            ['web', ['no-any', 'query-keys']],
        ])
        expect(answersByRepo([])).toEqual([])
    })
})

describe('answersLine', () => {
    it("names one list's repository, or counts several, then each answer given, in canopy checklist's order", () => {
        expect(answersLine(ANSWERS.slice(0, 3))).toBe('api · 2 pass · 1 held')
        expect(answersLine(ANSWERS)).toBe('2 repositories · 2 pass · 1 fixed · 1 held · 1 unanswered')
    })
})

describe('checklistFigures', () => {
    it('sums the items given, held, and unanswered over every repository', () => {
        const items = [
            item('api', 'a', { reminded: 3, held: 1, unanswered: 0 }),
            item('web', 'b', { reminded: 2, held: 0, unanswered: 2 }),
        ]
        expect(checklistFigures(items)).toEqual({ reminded: 5, held: 1, unanswered: 2 })
        expect(checklistFigures([])).toEqual({ reminded: 0, held: 0, unanswered: 0 })
    })
})

describe('checklistVerdict', () => {
    it('says argue of an item held twice or more, however few runs were given it', () => {
        expect(checklistVerdict(item('api', 'a', { reminded: 2, passed: 0, held: 2 }))?.word).toBe('argue')
        expect(checklistVerdict(item('api', 'a', { reminded: 2, passed: 1, held: 1 }))).toBeNull()
    })

    it('says drop? of an item given ten times or more that is mostly n/a, or never failed', () => {
        expect(checklistVerdict(item('api', 'a', { reminded: 10, passed: 10 }))).toEqual({
            word: 'drop?',
            why: 'Never failed in 10 answers: the runs pay tokens to agree with it',
        })
        expect(checklistVerdict(item('api', 'a', { reminded: 10, passed: 3, fixed: 1, not_applicable: 6 }))?.word).toBe(
            'drop?',
        )
        // Under ten runs, never failing may be luck; and one that fails now and then earns its place.
        expect(checklistVerdict(item('api', 'a', { reminded: 9, passed: 9 }))).toBeNull()
        expect(checklistVerdict(item('api', 'a', { reminded: 10, passed: 9, fixed: 1 }))).toBeNull()
        // n/a by half of what was answered is not mostly; the unanswered are not answers.
        expect(checklistVerdict(item('api', 'a', { reminded: 12, passed: 4, fixed: 1, not_applicable: 5 }))).toBeNull()
        expect(
            checklistVerdict(item('api', 'a', { reminded: 12, passed: 1, fixed: 1, not_applicable: 5, unanswered: 5 }))
                ?.word,
        ).toBe('drop?')
        // A list no run answered says nothing.
        expect(checklistVerdict(item('api', 'a', { reminded: 10, passed: 0, unanswered: 10 }))).toBeNull()
    })
})

describe('checklistSort and sortGroups', () => {
    it('keeps an order the page offers, and drops the default and the rest', () => {
        expect(checklistSort('held')).toBe('held')
        expect(checklistSort('na')).toBe('na')
        expect(checklistSort('list')).toBeUndefined()
        expect(checklistSort('cost')).toBeUndefined()
    })

    it("orders each repository's items the most first, ties in the list's order, the repositories as they were", () => {
        const groups = itemsByRepo(
            [
                item('api', 'a', { reminded: 4, held: 1, not_applicable: 1 }),
                item('api', 'b', { reminded: 2, held: 2, not_applicable: 1 }),
                item('api', 'c', { reminded: 4, held: 0 }),
                item('web', 'd', { held: 0, unanswered: 1 }),
            ],
            undefined,
        )
        const ids = (sort: Parameters<typeof sortGroups>[1]) =>
            sortGroups(groups, sort).map((g) => [g.repo, g.items.map((i) => i.item)])
        expect(ids('list')).toEqual([
            ['api', ['a', 'b', 'c']],
            ['web', ['d']],
        ])
        expect(ids('held')).toEqual([
            ['api', ['b', 'a', 'c']],
            ['web', ['d']],
        ])
        // b's one n/a is half its runs; a's, a quarter.
        expect(ids('na')[0]).toEqual(['api', ['b', 'a', 'c']])
    })
})

describe('pickedItem', () => {
    it('finds the item a key names among those the filter keeps', () => {
        const groups = itemsByRepo(ITEMS, 'api')
        expect(itemKey(ITEMS[0] ?? item('', ''))).toBe('api:newspaper')
        expect(pickedItem(groups, 'api:doc-comments')?.item).toBe('doc-comments')
        expect(pickedItem(groups, 'web:no-any')).toBeUndefined()
        expect(pickedItem(groups, undefined)).toBeUndefined()
    })
})

function week(repo: string, id: string, at: string, extra: Partial<ChecklistWeek> = {}): ChecklistWeek {
    return {
        repo,
        item: id,
        week: at,
        reminded: 0,
        passed: 0,
        fixed: 0,
        held: 0,
        not_applicable: 0,
        unanswered: 0,
        ...extra,
    }
}

describe('answersByWeek and weekBars', () => {
    const WEEKS = [
        week('api', 'newspaper', '2026-W40', { reminded: 2, passed: 1, held: 1 }),
        week('api', 'newspaper', '2026-W41'),
        week('web', 'no-any', '2026-W40', { reminded: 1, fixed: 1 }),
        week('web', 'no-any', '2026-W41', { reminded: 3, passed: 3 }),
    ]

    it("sums every item's weeks the filter keeps, or keeps the picked item's, every week of the window kept", () => {
        expect(answersByWeek(WEEKS, undefined, undefined).map((w) => [w.week, w.reminded, w.passed])).toEqual([
            ['2026-W40', 3, 1],
            ['2026-W41', 3, 3],
        ])
        expect(answersByWeek(WEEKS, undefined, 'api').map((w) => [w.week, w.reminded])).toEqual([
            ['2026-W40', 2],
            ['2026-W41', 0],
        ])
        expect(
            answersByWeek(WEEKS, { repo: 'web', item: 'no-any' }, 'api').map((w) => [w.week, w.reminded, w.fixed]),
        ).toEqual([
            ['2026-W40', 1, 1],
            ['2026-W41', 3, 0],
        ])
    })

    it('draws a bar a week, named by its week, its answers stacked in the table order', () => {
        const [first] = weekBars(answersByWeek(WEEKS, undefined, 'api'))
        expect(first?.label).toBe('W40')
        expect(first?.hint).toBe('2026-W40: 2 items given · 1 pass · 1 held')
        expect(first?.segments.map((s) => [s.key, s.value])).toEqual([
            ['passed', 1],
            ['fixed', 0],
            ['held', 1],
            ['not_applicable', 0],
            ['unanswered', 0],
        ])
    })

    it('says an item with no answers has none', () => {
        expect(answersWords(item('api', 'a', { passed: 0 }))).toBe('no answers')
    })
})
