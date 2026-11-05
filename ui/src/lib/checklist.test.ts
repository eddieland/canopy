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
        held_by: 0,
        paths: [],
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
    it('says argue of an item held often, by two tickets or more', () => {
        expect(checklistVerdict(item('api', 'a', { reminded: 2, passed: 0, held: 2, held_by: 2 }))).toEqual({
            word: 'argue',
            why: 'Held 2 of 2 times it applied, over 2 tickets: runs keep finding the rule wrong for the diff',
        })
        expect(checklistVerdict(item('api', 'a', { reminded: 12, passed: 9, held: 3, held_by: 2 }))?.word).toBe('argue')
        // One ticket's runs, held over the same diff, are one disagreement.
        expect(checklistVerdict(item('api', 'a', { reminded: 2, passed: 0, held: 2, held_by: 1 }))).toBeNull()
        // Twice in forty is a run's judgment now and then, however many tickets.
        expect(checklistVerdict(item('api', 'a', { reminded: 40, passed: 38, held: 2, held_by: 2 }))).toBeNull()
        // A share, not a count: twice as many answers of the same share argue as much.
        expect(checklistVerdict(item('api', 'a', { reminded: 80, passed: 70, held: 10, held_by: 5 }))?.word).toBe(
            'argue',
        )
    })

    it('says earning of an item fixed often, and argue first of one held as often', () => {
        expect(checklistVerdict(item('api', 'a', { reminded: 10, passed: 6, fixed: 4 }))).toEqual({
            word: 'earning',
            why: 'Fixed 4 of 10 times it applied: each a review comment nobody had to write',
        })
        expect(checklistVerdict(item('api', 'a', { reminded: 10, passed: 9, fixed: 1 }))).toBeNull()
        expect(checklistVerdict(item('api', 'a', { reminded: 40, passed: 38, fixed: 2 }))).toBeNull()
        expect(
            checklistVerdict(item('api', 'a', { reminded: 10, passed: 4, fixed: 3, held: 3, held_by: 3 }))?.word,
        ).toBe('argue')
    })

    it('says drop? only of an item that never failed in thirty answers where it applied', () => {
        expect(checklistVerdict(item('api', 'a', { reminded: 30, passed: 30 }))).toEqual({
            word: 'drop?',
            why: 'Never failed in 30 answers where it applied: runs pay tokens to agree',
        })
        expect(checklistVerdict(item('api', 'a', { reminded: 29, passed: 29 }))).toEqual({
            word: 'too few',
            why: 'No failure in 29 answers where it applied: under 30, a rule kept and a rule not yet met look alike',
        })
        // An n/a is not a pass: forty answers, ten where it applied.
        expect(
            checklistVerdict(item('api', 'a', { reminded: 40, passed: 10, not_applicable: 30, paths: ['m/'] })),
        ).toEqual({
            word: 'too few',
            why: 'No failure in 10 answers where it applied: under 30, a rule kept and a rule not yet met look alike',
        })
        expect(
            checklistVerdict(item('api', 'a', { reminded: 12, passed: 0, not_applicable: 12, paths: ['m/'] })),
        ).toEqual({ word: 'too few', why: 'It has not applied to a diff yet' })
    })

    it('says narrow of an item without paths that is mostly n/a, and nothing of the n/a of one with paths', () => {
        expect(checklistVerdict(item('api', 'a', { reminded: 10, passed: 3, fixed: 1, not_applicable: 6 }))).toEqual({
            word: 'narrow',
            why: 'n/a 6 of 10 answers, and it names no paths: give it the ones it is for',
        })
        const scoped = item('api', 'a', { reminded: 10, passed: 3, fixed: 1, not_applicable: 6, paths: ['m/'] })
        expect(checklistVerdict(scoped)).toBeNull()
        // A list that no longer holds the item cannot say whether it names paths.
        expect(checklistVerdict({ ...scoped, paths: null })).toBeNull()
        // Half is not mostly, and under ten answers mostly may be luck.
        expect(checklistVerdict(item('api', 'a', { reminded: 10, passed: 4, fixed: 1, not_applicable: 5 }))).toBeNull()
        expect(checklistVerdict(item('api', 'a', { reminded: 9, passed: 2, fixed: 1, not_applicable: 6 }))).toBeNull()
    })

    it('says too few of an item most runs said nothing of, and nothing of one no run was given', () => {
        expect(
            checklistVerdict(item('api', 'a', { reminded: 12, passed: 1, held: 2, held_by: 2, unanswered: 5 })),
        ).toEqual({
            word: 'too few',
            why: '5 of 12 runs said nothing of it: too few answers are left to judge',
        })
        expect(
            checklistVerdict(item('api', 'a', { reminded: 12, passed: 2, held: 6, held_by: 2, unanswered: 4 }))?.word,
        ).toBe('argue')
        expect(checklistVerdict(item('api', 'a', { reminded: 0, passed: 0 }))).toBeNull()
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
