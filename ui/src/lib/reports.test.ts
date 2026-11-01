import { describe, expect, it } from 'vitest'

import { mockReportMonth, mockReportTicket, mockReportTokens } from '@/api/mocks'
import type { ReportMonth } from '@/api/types'
import { DEFAULT_CLOCK } from '@/lib/clock'
import { stamp } from '@/lib/time'

import {
    clockShare,
    hoursText,
    medianText,
    monthLabel,
    outsideHint,
    pickedMonth,
    DELIVERY_TRENDS,
    fittedMonths,
    monthBars,
    monthChange,
    monthShare,
    reportLine,
    reportMonth,
    sinceText,
    trendPointHint,
    reportSpan,
    reviewWaitHint,
    sentTokens,
    toLandHint,
    wroteTokens,
} from './reports'

const TOKENS = mockReportTokens
const month = mockReportMonth
const ticket = mockReportTicket

describe('reportSpan', () => {
    it('keeps a span the page offers, as a number or its digits', () => {
        expect(reportSpan(6)).toBe(6)
        expect(reportSpan('24')).toBe(24)
        expect(reportSpan(12)).toBe(12)
        expect(reportSpan(7)).toBeUndefined()
        expect(reportSpan('six')).toBeUndefined()
    })
})

describe('reportMonth', () => {
    it('keeps a month written YYYY-MM, and nothing else', () => {
        expect(reportMonth('2026-10')).toBe('2026-10')
        expect(reportMonth('2026-13')).toBeUndefined()
        expect(reportMonth('2026-1')).toBeUndefined()
        expect(reportMonth(202_610)).toBeUndefined()
    })
})

describe('pickedMonth', () => {
    const months = [month('2026-09', 1), month('2026-10', 2)]

    it('shows the month chosen, else the latest', () => {
        expect(pickedMonth(months, '2026-09')?.month).toBe('2026-09')
        expect(pickedMonth(months, undefined)?.month).toBe('2026-10')
        expect(pickedMonth(months, '2025-01')?.month).toBe('2026-10')
        expect(pickedMonth([], undefined)).toBeUndefined()
    })
})

describe('monthLabel', () => {
    it('names a month short or long', () => {
        expect(monthLabel('2026-10')).toBe('Oct 2026')
        expect(monthLabel('2026-01', 'long')).toBe('January 2026')
    })
})

describe('reportLine', () => {
    it('says what the latest month cost and landed', () => {
        const landed = [{ key: 'ABC-1' }, { key: 'ABC-2' }] as ReportMonth['landed']
        expect(reportLine([month('2026-09', 1), month('2026-10', 12.5, { landed, pull_requests: 1 })])).toBe(
            '$12.50 in October 2026 · 2 tickets landed · 1 PR · $1.00 in September',
        )
        // The month before, in another year, says its year.
        expect(reportLine([month('2025-12', 3), month('2026-01', 1)])).toBe(
            '$1.00 in January 2026 · no tickets landed · no PRs · $3.00 in December 2025',
        )
        expect(reportLine([month('2026-10', null)])).toBe('– in October 2026 · no tickets landed · no PRs')
        expect(reportLine([])).toBe('')
    })
})

describe('tokens', () => {
    it('counts what was sent, the cache both ways included, and what was written, reasoning included', () => {
        expect(sentTokens(TOKENS)).toBe(10_000)
        expect(wroteTokens(TOKENS)).toBe(250)
    })
})

describe('hoursText', () => {
    it('says minutes under an hour, hours under two days, and days past them', () => {
        expect(hoursText(null)).toBe('–')
        expect(hoursText(0.5)).toBe('30m')
        expect(hoursText(5.25)).toBe('5.3h')
        expect(hoursText(72)).toBe('3.0d')
    })
})

describe('medianText', () => {
    it('writes a whole median whole, and a half with its tenth', () => {
        expect(medianText(null)).toBe('–')
        expect(medianText(3)).toBe('3')
        expect(medianText(2.5)).toBe('2.5')
    })
})

describe('outsideHint', () => {
    it('says what the row counts, as of the last read of the sessions, or that none is read yet', () => {
        const at = '2026-10-08T11:55:00Z'
        expect(outsideHint(at, DEFAULT_CLOCK)).toBe(
            "The runtime's sessions none of canopy's runs started, yours among them, counted in sessions, not runs, " +
                `as of ${stamp(at, DEFAULT_CLOCK)}.`,
        )
        expect(outsideHint(null, DEFAULT_CLOCK)).toMatch(/canopy loop has not read them yet, so none is counted\.$/u)
    })
})

describe('which clock a figure ran on', () => {
    const github = ticket('ABC-1', { merged_at: '2026-10-03T15:00:00Z', awaiting_review_at: '2026-09-29T16:00:00Z' })
    const proxied = ticket('ABC-2')
    const unknown = ticket('ABC-3', { hours_to_land: null, review_wait_hours: null })

    it("names GitHub's time where canopy kept one, else the proxy that stood in", () => {
        expect(toLandHint(github)).toBe("To its PR's merge, as GitHub timed it")
        expect(toLandHint(proxied)).toMatch(/^To the tick that marked it done/u)
        expect(reviewWaitHint(github)).toMatch(/^From when its PR began waiting on a review, as GitHub timed it/u)
        expect(reviewWaitHint(proxied)).toMatch(/^From the end of its first worker run that ended done/u)
        expect([toLandHint(unknown), reviewWaitHint(unknown)]).toEqual([undefined, undefined])
    })

    it("counts a month's figures that ran on GitHub's clock, leaving out the tickets with none", () => {
        expect(clockShare(month('2026-10', 1, { landed: [github, proxied, unknown] }), 'to land')).toBe(
            "1 of 2 from GitHub's times, the rest from proxies",
        )
        expect(clockShare(month('2026-10', 1, { landed: [github, github] }), 'review wait')).toBe(
            "All 2 from GitHub's times",
        )
        expect(clockShare(month('2026-10', 1, { landed: [proxied] }), 'review wait')).toBe(
            'From a proxy: canopy kept no time from GitHub',
        )
        expect(clockShare(month('2026-10', 1, { landed: [unknown] }), 'to land')).toBeUndefined()
    })
})

describe('fittedMonths', () => {
    it('opens on the months from the first that holds anything, gaps after it kept', () => {
        const months = [
            month('2026-05', null),
            month('2026-06', null),
            month('2026-07', 2),
            month('2026-08', null),
            month('2026-09', null, { landed: [ticket('ABC-1')] }),
        ]
        expect(fittedMonths(months).map((m) => m.month)).toEqual(['2026-07', '2026-08', '2026-09'])
        expect(sinceText(fittedMonths(months))).toBe('since July 2026')
    })

    it('keeps the latest month alone when none holds anything', () => {
        expect(fittedMonths([month('2026-09', null), month('2026-10', null)]).map((m) => m.month)).toEqual(['2026-10'])
        expect(sinceText([])).toBe('')
    })
})

describe('monthBars', () => {
    it("stacks each month's kinds in the spend fills, the sessions outside canopy on top, named on hover", () => {
        const october = month('2026-10', 10, {
            kinds: [
                { kind: 'overseer', runs: 2, cost_usd: 1, tokens: TOKENS },
                { kind: 'workers', runs: 3, cost_usd: 7, tokens: TOKENS },
            ],
            outside: { sessions: 1, cost_usd: 2, tokens: TOKENS },
        })
        const [bar] = monthBars([october])
        expect(bar?.label).toBe('Oct 2026')
        expect(bar?.total).toBe(10)
        expect(bar?.segments.filter((s) => s.value > 0).map((s) => [s.key, s.fill, s.value])).toEqual([
            ['overseer', 'bg-spend-overseer', 1],
            ['workers', 'bg-spend-workers', 7],
            ['outside', 'bg-spend-outside', 2],
        ])
        expect(bar?.hint).toBe('October 2026: $10.00, overseer $1.00, workers $7.00, outside canopy $2.00')
        expect(monthBars([month('2026-09', null)])[0]?.hint).toBe('September 2026: nothing reported')
    })
})

describe('month over month', () => {
    it("says how a month's cost moved on the month before's, on its cell's hover", () => {
        const before = month('2026-09', 13.99)
        expect(monthChange(15.76, before, (m) => m.cost_usd)).toBe('+$1.77 on September 2026')
        expect(monthChange(13.99, before, (m) => m.cost_usd)).toBe('same as September 2026')
        expect(monthChange(10, before, (m) => m.cost_usd)).toBe('−$3.99 on September 2026')
        expect(monthChange(10, undefined, (m) => m.cost_usd)).toBeUndefined()
        expect(monthChange(10, month('2026-09', null), (m) => m.cost_usd)).toBeUndefined()
    })

    it("draws a row's share of the month's whole", () => {
        expect(monthShare(4, 8)).toBe(50)
        expect(monthShare(null, 8)).toBe(0)
        expect(monthShare(4, null)).toBe(0)
    })
})

describe('Delivery trends', () => {
    it("says a month's point, and for a time which clock its figures ran on", () => {
        const [iterations, , toLand] = DELIVERY_TRENDS
        const october = month('2026-10', 1, {
            median_iterations: 2.5,
            median_hours_to_land: 20.8,
            landed: [ticket('ABC-1', { merged_at: '2026-10-04T10:00:00Z' }), ticket('ABC-2')],
        })
        expect(iterations === undefined ? '' : trendPointHint(october, iterations)).toBe('Oct 2026: 2.5')
        expect(toLand === undefined ? '' : trendPointHint(october, toLand)).toBe(
            "Oct 2026: 20.8h · 1 of 2 from GitHub's times, the rest from proxies",
        )
    })
})
