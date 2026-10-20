import { describe, expect, it } from 'vitest'

import type { SpendCosts, SpendDay } from '@/api/types'

import {
    chartTop,
    dayHint,
    dayLabel,
    dayName,
    dearestDay,
    doneText,
    seriesCost,
    SERIES,
    shareText,
    spendLine,
    spendWindow,
    windowId,
    windowName,
} from './spend'

const NONE: SpendCosts = {
    overseer: null,
    idle: null,
    dry_run: null,
    workers: null,
    triage: null,
    plans: null,
    chores: null,
    reviews: null,
    total: null,
}

function day(name: string, costs: Partial<SpendCosts>): SpendDay {
    return { day: name, costs: { ...NONE, ...costs }, done: 0 }
}

describe('spend', () => {
    it("takes idle ticks' part out of the overseer's, so the series sum to the day's total", () => {
        const costs: SpendCosts = { ...NONE, overseer: 1.5, idle: 0.5, workers: 2, dry_run: 0.25, total: 3.75 }
        expect(seriesCost(costs, 'idle')).toBe(0.5)
        expect(seriesCost(costs, 'overseer')).toBe(1)
        expect(SERIES.reduce((sum, s) => sum + seriesCost(costs, s.key), 0)).toBe(3.75)
        expect(seriesCost(NONE, 'overseer')).toBe(0)
    })

    it("tops the chart at the dearest day's total, or 0 for a window with nothing reported", () => {
        expect(chartTop([day('2026-10-07', { total: 1 }), day('2026-10-08', { total: 4.5 })])).toBe(4.5)
        expect(chartTop([day('2026-10-08', {})])).toBe(0)
        expect(chartTop([])).toBe(0)
    })

    it('says a day on hover with each series it has', () => {
        expect(dayHint(day('2026-10-07', { overseer: 1, idle: 0.25, reviews: 0.5, total: 1.5 }))).toBe(
            'Oct 7: $1.50, overseer $1.00 (idle ticks $0.25), reviews $0.50',
        )
        expect(dayHint(day('2026-10-02', {}))).toBe('Oct 2: nothing reported')
        expect(dayHint(day('2026-10-08T14', { workers: 2, total: 2 }))).toBe('Oct 8, 14:00: $2.00, workers $2.00')
    })

    it('names a day as the axis does, whatever the zone', () => {
        expect(dayLabel('2026-10-01')).toBe('Oct 1')
        expect(dayLabel('2026-12-31')).toBe('Dec 31')
    })

    it('names an hour by its time on the axis, and with its day in full', () => {
        expect(dayLabel('2026-10-08T09')).toBe('09:00')
        expect(dayName('2026-10-08T09')).toBe('Oct 8, 09:00')
        expect(dayName('2026-10-08')).toBe('Oct 8')
    })

    it('finds the dearest day, the latest of equals, so its total is said over its bar', () => {
        const week = [
            day('2026-10-06', { total: 2 }),
            day('2026-10-07', { total: 4.5 }),
            day('2026-10-08', { total: 1 }),
        ]
        expect(dearestDay(week)).toBe(1)
        expect(dearestDay([day('2026-10-07', { total: 3 }), day('2026-10-08', { total: 3 })])).toBe(1)
        expect(dearestDay([day('2026-10-08', {})])).toBe(-1)
    })

    it('takes only the windows the page offers, hours before days', () => {
        expect(spendWindow({ days: '30' })).toEqual({ days: 30 })
        expect(spendWindow({ days: 7 })).toEqual({ days: 7 })
        expect(spendWindow({ hours: '24' })).toEqual({ hours: 24 })
        expect(spendWindow({ hours: 24, days: 30 })).toEqual({ hours: 24 })
        expect(spendWindow({ days: '8' })).toBeUndefined()
        expect(spendWindow({ hours: 12 })).toBeUndefined()
        expect(spendWindow({})).toBeUndefined()
    })

    it('names a window and gives it an id, in hours or in days', () => {
        expect([windowName({ hours: 24 }), windowName({ days: 7 }), windowName({ days: 1 })]).toEqual([
            '24 hours',
            '7 days',
            '1 day',
        ])
        expect([windowId({ hours: 24 }), windowId({ days: 30 })]).toEqual(['24h', '30'])
    })

    it('says a share as a whole percent', () => {
        expect(shareText(0.4123)).toBe('41%')
        expect(shareText(null)).toBe('–')
    })

    it('says when and how a ticket was marked done, by its local day, and nothing for one that was not', () => {
        // Noon UTC is the same day in every zone but the farthest few, so the test reads alike wherever it runs.
        expect(doneText({ done: 'merged', done_at: '2026-10-07T12:00:00Z' })).toBe('Oct 7, merged')
        expect(doneText({ done: 'closed', done_at: '2026-10-08T12:10:00Z' })).toBe('Oct 8, closed')
        expect(doneText({ done: null, done_at: null })).toBe('')
    })

    it("says the window's state: what it cost and what it got done", () => {
        expect(spendLine({ days: 7, hours: null, done: 2, totals: { ...NONE, total: 10.512 } })).toBe(
            '$10.51 over 7 days · 2 tickets done',
        )
        expect(spendLine({ days: 30, hours: null, done: 0, totals: NONE })).toBe('– over 30 days · no tickets done')
        expect(spendLine({ days: null, hours: 24, done: 1, totals: { ...NONE, total: 2 } })).toBe(
            '$2.00 over 24 hours · 1 ticket done',
        )
    })

    it('names each series once, the same in the totals, the legend, and the table', () => {
        const labels = SERIES.map((s) => s.label)
        expect(new Set(labels).size).toBe(labels.length)
        expect(labels).toEqual([
            'idle ticks',
            'overseer',
            'workers',
            'plan triage',
            'plans',
            'chores',
            'reviews',
            'dry runs',
        ])
    })
})
