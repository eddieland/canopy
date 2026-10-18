import { describe, expect, it } from 'vitest'

import type { DiffFile, DiffLine } from '@/api/types'

import {
    DIFF_BUDGET,
    fileFoldedText,
    foldedText,
    foldLabel,
    lineCount,
    nextStep,
    pieces,
    reveal,
    shownAtFirst,
} from './review-folds'

/** A file of hunks with these many lines each, every line added, numbered on the new side from 1 across them. */
function file(...hunks: number[]): DiffFile {
    let n = 0
    return {
        path: 'src/a.ts',
        old_path: null,
        binary: false,
        hunks: hunks.map((count) => ({
            header: '',
            lines: Array.from({ length: count }, (): DiffLine => {
                n += 1
                return { kind: 'add', old: null, new: n, text: '' }
            }),
        })),
    }
}

describe('shownAtFirst', () => {
    it('shows every line of a diff within the budget', () => {
        const files = [file(3, 4), file(), file(DIFF_BUDGET.page - 7)]
        expect(shownAtFirst(files, new Map())).toStrictEqual([
            [{ from: 0, to: 7 }],
            [],
            [{ from: 0, to: DIFF_BUDGET.page - 7 }],
        ])
    })

    it("shows a long diff's findings in context, then whole files that fit, then files' first lines", () => {
        const big = DIFF_BUDGET.page * 2
        const files = [file(big), file(100), file(big), file(50)]
        // A finding on line 3000 of the first file, and one on line 5 of the third.
        const anchored = new Map([
            [0, new Map([[3000, null]])],
            [2, new Map([[5, null]])],
        ])
        const shown = shownAtFirst(files, anchored)
        const around = 2 * DIFF_BUDGET.context + 1
        // What is left after the findings and the two small files goes to the first lines of the first big file.
        const left = DIFF_BUDGET.page - around - (5 + DIFF_BUDGET.context) - 100 - 50
        expect(shown).toStrictEqual([
            [
                { from: 0, to: left },
                { from: 2999 - DIFF_BUDGET.context, to: 2999 + DIFF_BUDGET.context + 1 },
            ],
            [{ from: 0, to: 100 }],
            [{ from: 0, to: 5 + DIFF_BUDGET.context }],
            [{ from: 0, to: 50 }],
        ])
        expect(shown.flat().reduce((sum, s) => sum + s.to - s.from, 0)).toBe(DIFF_BUDGET.page)
    })

    it('counts lines already shown around a finding toward the first lines it shows', () => {
        const files = [file(DIFF_BUDGET.page * 2)]
        const shown = shownAtFirst(files, new Map([[0, new Map([[30, null]])]]))
        expect(shown).toStrictEqual([[{ from: 0, to: DIFF_BUDGET.page }]])
    })

    it('ignores a finding on a line the file does not show', () => {
        const files = [file(DIFF_BUDGET.page + 1)]
        const shown = shownAtFirst(files, new Map([[0, new Map([[999_999, null]])]]))
        expect(shown).toStrictEqual([[{ from: 0, to: DIFF_BUDGET.page }]])
    })
})

describe('reveal', () => {
    it('keeps spans in order and merges those that touch or overlap', () => {
        expect(reveal([{ from: 10, to: 20 }], { from: 0, to: 5 })).toStrictEqual([
            { from: 0, to: 5 },
            { from: 10, to: 20 },
        ])
        expect(reveal([{ from: 0, to: 5 }], { from: 5, to: 9 })).toStrictEqual([{ from: 0, to: 9 }])
        expect(
            reveal(
                [
                    { from: 0, to: 5 },
                    { from: 8, to: 12 },
                ],
                { from: 4, to: 9 },
            ),
        ).toStrictEqual([{ from: 0, to: 12 }])
    })

    it('drops an empty span', () => {
        expect(reveal([], { from: 3, to: 3 })).toStrictEqual([])
    })
})

describe('nextStep', () => {
    it("shows a fold's first lines, a step at most", () => {
        expect(nextStep({ from: 10, to: 20 })).toStrictEqual({ from: 10, to: 20 })
        expect(nextStep({ from: 10, to: 10_000 })).toStrictEqual({ from: 10, to: 10 + DIFF_BUDGET.step })
    })
})

describe('foldLabel', () => {
    it('says how many lines a click shows, and of how many when that is a step of them', () => {
        expect(foldLabel({ from: 0, to: 1 })).toBe('Show 1 hidden line')
        expect(foldLabel({ from: 40, to: 100 })).toBe('Show 60 hidden lines')
        expect(foldLabel({ from: 1960, to: 14_989 })).toBe('Show 500 of 13,029 hidden lines')
    })
})

describe('fileFoldedText', () => {
    const FINDINGS = ['finding', 'findings'] as const

    it('counts the lines and cards a folded file hides', () => {
        expect(fileFoldedText(1, 0, FINDINGS)).toBe('1 line folded away')
        expect(fileFoldedText(13_029, 0, FINDINGS)).toBe('13,029 lines folded away')
        expect(fileFoldedText(40, 1, FINDINGS)).toBe('40 lines and 1 finding folded away')
        expect(fileFoldedText(40, 3, ['thread', 'threads'])).toBe('40 lines and 3 threads folded away')
    })
})

describe('foldedText', () => {
    it('groups its counts by thousands', () => {
        expect(foldedText(2000, 30_000)).toContain('the page shows 2,000 of its 30,000 lines at first')
    })
})

describe('pieces', () => {
    it('draws every hunk and its lines when all are shown', () => {
        const f = file(2, 3)
        expect(pieces(f, [{ from: 0, to: lineCount(f) }])).toStrictEqual([
            { kind: 'hunk', hunk: 0 },
            { kind: 'lines', hunk: 0, from: 0, to: 2 },
            { kind: 'hunk', hunk: 1 },
            { kind: 'lines', hunk: 1, from: 0, to: 3 },
        ])
    })

    it('folds a file with nothing shown into one fold, its hunk headers in it', () => {
        expect(pieces(file(2, 3, 4), [])).toStrictEqual([{ kind: 'fold', span: { from: 0, to: 9 } }])
    })

    it('folds within a hunk, and runs a fold at a hunk end through the hunks after it with nothing shown', () => {
        // Hunks of lines 0-9, 10-14, 15-19, 20-29: lines 3-5 and 22-24 shown.
        const f = file(10, 5, 5, 10)
        const shown = [
            { from: 3, to: 6 },
            { from: 22, to: 25 },
        ]
        expect(pieces(f, shown)).toStrictEqual([
            { kind: 'hunk', hunk: 0 },
            { kind: 'fold', span: { from: 0, to: 3 } },
            { kind: 'lines', hunk: 0, from: 3, to: 6 },
            { kind: 'fold', span: { from: 6, to: 20 } },
            { kind: 'hunk', hunk: 3 },
            { kind: 'fold', span: { from: 20, to: 22 } },
            { kind: 'lines', hunk: 3, from: 2, to: 5 },
            { kind: 'fold', span: { from: 25, to: 30 } },
        ])
    })

    it('draws nothing for a hunk with no lines, as a cut at the line bound can leave', () => {
        const f = file(2, 0, 2)
        expect(pieces(f, [{ from: 0, to: 4 }])).toStrictEqual([
            { kind: 'hunk', hunk: 0 },
            { kind: 'lines', hunk: 0, from: 0, to: 2 },
            { kind: 'hunk', hunk: 2 },
            { kind: 'lines', hunk: 2, from: 0, to: 2 },
        ])
    })
})
