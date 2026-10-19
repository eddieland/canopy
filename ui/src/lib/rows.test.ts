import { describe, expect, it } from 'vitest'

import { fitColumn, ROW_COLUMNS, ROW_TIERS, rowLayout, rowLineFrom, rowTemplate, rowTiers } from './rows'
import type { RowKind, RowTier } from './rows'

const FREE = 'minmax(8rem,1fr)'
// The free column, at the usual floor or one of its kind's own.
const ANY_FREE = /^minmax\([\d.]+rem,1fr\)$/u
const KINDS = Object.keys(ROW_COLUMNS) as RowKind[]

describe('rowTemplate', () => {
    it('names each column before its width, and the end after the last', () => {
        expect(rowTemplate('chore', 'xl')).toBe(`[name] 10rem [state] ${FREE} [findings] 14rem [end]`)
    })

    it('lends a column it leaves out its name to the next one shown, or to the end', () => {
        expect(rowTemplate('chore')).toBe(`[name] 10rem [state] ${FREE} [findings end]`)
        expect(rowTemplate('ticket', 'lg')).toBe(`[run] 8rem [key] 6rem [phase access title] ${FREE} [age] 6rem [end]`)
    })

    it('gives every kind exactly one free column, so its fixed ones line up row to row', () => {
        for (const columns of Object.values(ROW_COLUMNS)) {
            expect(columns.filter(([, width]) => ANY_FREE.test(width))).toHaveLength(1)
        }
    })

    it('gives the age and the cost one width in every kind, so they line up from list to list', () => {
        const kinds: (readonly (readonly [string, string, number?])[])[] = Object.values(ROW_COLUMNS)
        const widths = (name: string) =>
            new Set(kinds.flatMap((columns) => columns.filter(([n]) => n === name).map(([, width]) => width)))
        expect(widths('age')).toEqual(new Set(['6rem']))
        expect(widths('cost')).toEqual(new Set(['4rem']))
    })

    it('leads with the state wherever a row has one, then its own id', () => {
        const kinds: Partial<Record<RowKind, string[]>> = {
            run: ['state', 'run'],
            tick: ['state', 'id'],
            review: ['verdict', 'id'],
            'own-review': ['verdict', 'id'],
            ticket: ['run', 'key'],
            'pull-request': ['state', 'pr'],
            memory: ['state', 'id'],
            'memory-across': ['state', 'id'],
            'thread-draft': ['state', 'id'],
        }
        for (const [kind, lead] of Object.entries(kinds)) {
            expect(ROW_COLUMNS[kind as RowKind].slice(0, 2).map(([name]) => name)).toEqual(lead)
        }
    })

    it('names no column twice in a kind', () => {
        for (const columns of Object.values(ROW_COLUMNS)) {
            const names = columns.map(([name]) => name)
            expect(new Set(names).size).toBe(names.length)
        }
    })
})

describe('rowTiers', () => {
    it('lets the chip go first on a ticket, then the phase, and keeps the title', () => {
        const tiers = rowTiers('ticket')
        expect(tiers.get('access')).toBe('4xl')
        expect(tiers.get('phase')).toBe('3xl')
        expect(tiers.has('title')).toBe(false)
    })

    it('lets money and tokens go before what names a row', () => {
        const run = rowTiers('run')
        expect(run.get('cost')).toBe('4xl')
        expect(run.get('run')).toBe('md')
        const tick = rowTiers('tick')
        expect(tick.get('tokens')).toBe('4xl')
        expect(tick.has('id')).toBe(false)
    })

    it("keeps a run's age in a list at half a monitor, letting its cost and chips go first", () => {
        // A list in an 820px window is about 44rem wide: at least @2xl, under @3xl.
        const run = rowTiers('run')
        expect(run.get('cost')).toBe('4xl')
        expect(run.get('kind')).toBe('3xl')
        expect(['sm', 'md', 'lg', 'xl', '2xl']).toContain(run.get('age'))
    })

    it("lets a PR's phase go before its title is cut to a word, and fits its PR column to the list", () => {
        const pr = rowTiers('pull-request')
        expect(pr.get('phase')).toBe('4xl')
        expect(pr.has('title')).toBe(false)
        expect(rowTemplate('pull-request', '4xl')).toContain('[pr] var(--pr-width,11rem) [phase]')
    })

    it("lets what holds a slot go before its branch is cut, and keeps the slot's age", () => {
        const worktree = rowTiers('worktree')
        expect(worktree.get('holder')).toBe('3xl')
        expect(worktree.has('branch')).toBe(false)
        expect(['sm', 'md', 'lg', 'xl', '2xl']).toContain(worktree.get('age'))
        expect(rowTemplate('worktree', '2xl')).toBe(
            '[state] 5rem [slot] 3.5rem [holder branch] minmax(12rem,1fr) [age] 6rem [end]',
        )
    })

    it('fits every column a list shows at a tier in that tier, the free one at its floor', () => {
        // A kind with an `auto` column cannot be summed, so none of its columns may give way.
        const giving = KINDS.filter((kind) => rowTiers(kind).size > 0)
        expect(giving.filter((kind) => Number.isNaN(least(kind, '4xl')))).toEqual([])
        for (const kind of giving) {
            for (const [tier, rem] of ROW_TIERS) {
                expect(least(kind, tier), `${kind} at @${tier}`).toBeLessThanOrEqual(rem)
            }
        }
    })

    it('shows every column at the widest tier, which a list in a 1280px window reaches', () => {
        for (const kind of KINDS) {
            expect(() => rowTiers(kind)).not.toThrow()
        }
    })

    it('never lets the free column give way, and orders the ones that do without a tie', () => {
        const kinds: (readonly (readonly [string, string, number?])[])[] = Object.values(ROW_COLUMNS)
        for (const columns of kinds) {
            const orders = columns.flatMap(([, , order]) => (order === undefined ? [] : [order]))
            expect(new Set(orders).size).toBe(orders.length)
            expect(columns.filter(([, width, order]) => ANY_FREE.test(width) && order !== undefined)).toEqual([])
        }
    })
})

describe('fitColumn', () => {
    it("sets a column as wide as the list's longest name in monospace, and what sits beside it", () => {
        // `acme/web#95`, 11 characters at 0.45rem, and a 1.25rem icon: 6.2rem, up to the next quarter.
        expect(fitColumn('pr', ['acme/api#7', 'acme/web#95'], 1.25)).toEqual({ '--pr-width': '6.25rem' })
    })

    it('never sets it wider than the column at its most, which a longer name is cut to', () => {
        expect(fitColumn('pr', ['a-long-organization/a-long-repository#12345'], 1.25)).toEqual({
            '--pr-width': '11rem',
        })
    })
})

describe('rowLayout', () => {
    it("sets a template per tier the kind's columns change at, and hides each left-out column's cell", () => {
        const { className, style } = rowLayout('chore')
        expect(style).toEqual({ '--row': rowTemplate('chore'), '--row-xl': rowTemplate('chore', 'xl') })
        expect(className.split(' ')).toEqual([
            'grid-cols-(--row)',
            '@xl:grid-cols-(--row-xl)',
            '@max-xl:[&>:nth-child(3)]:hidden',
        ])
    })

    it('needs no more places than index.css lists for Tailwind', () => {
        for (const columns of Object.values(ROW_COLUMNS)) {
            expect(columns.length).toBeLessThanOrEqual(8)
        }
    })
})

describe('rowLineFrom', () => {
    it('spans from the named column to the end', () => {
        expect(rowLineFrom('title')).toBe('col-[title/end]')
    })
})

/**
 * The least room in rem a row of `kind` takes at `tier`: its columns' least widths, its gaps, and its padding. Not a
 * number when a column is `auto`.
 */
function least(kind: RowKind, tier: RowTier): number {
    const shown = [...rowTemplate(kind, tier).matchAll(/\] (\S+)/gu)].map((match) => match[1] ?? '')
    const widths = shown.map((width) => Number(/([\d.]+)rem/u.exec(width)?.[1] ?? Number.NaN))
    return widths.reduce((sum, width) => sum + width, 1.5 + 0.75 * (widths.length - 1))
}
