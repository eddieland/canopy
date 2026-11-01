import { describe, expect, it } from 'vitest'

import type { SpendCosts, SpendDay, SpendModel, SpendMonth, SpendSessions, SpendTool } from '@/api/types'
import type { Clock } from '@/lib/clock'
import { stamp } from '@/lib/time'

import {
    alertMarks,
    alertsText,
    budgetPercent,
    budgetState,
    budgetPartsText,
    budgetDayText,
    budgetSpentText,
    budgetText,
    foldedText,
    paceText,
    spendWeeks,
    weekBars,
    weekName,
    weeksOffered,
    sessionsReadText,
    chartTop,
    dayHint,
    dayLabel,
    dayName,
    doneText,
    kindsOffered,
    comparedModels,
    listedModels,
    modelKind,
    modelKey,
    modelRows,
    monthName,
    perRun,
    seriesCost,
    SERIES,
    shareText,
    spendBars,
    spendLine,
    spendWindow,
    unpricedText,
    toolRows,
    unreadShare,
    workspacePerRun,
} from './spend'

const H24: Clock = { hours: '24', zone: false }
const H12: Clock = { hours: '12', zone: false }

// A By model row of the whole workspace, with no ticket's runs set beside the workspace's.
const ALONE = { workspace_runs: null, workspace_cost_usd: null, unread: false }

const NONE: SpendCosts = {
    overseer: null,
    idle: null,
    dry_run: null,
    workers: null,
    plans: null,
    chores: null,
    reviews: null,
    tasks: null,
    outside: null,
    total: null,
}

// A day as the server names it, its start at UTC midnight, which only an hour's name reads.
function day(name: string, costs: Partial<SpendCosts>): SpendDay {
    return { day: name, start: `${name}T00:00:00Z`, costs: { ...NONE, ...costs }, done: 0 }
}

// An hour of 2026-10-08 that starts at `hour` in the test's own zone, as the server names one in its own.
function hourOf(hour: number, costs: Partial<SpendCosts> = {}): SpendDay {
    const start = new Date(2026, 9, 8, hour).toISOString()
    return { day: `2026-10-08T${String(hour).padStart(2, '0')}`, start, costs: { ...NONE, ...costs }, done: 0 }
}

// A tool's calls in one kind's runs, its tokens estimated as the server does.
function tool(kind: SpendTool['kind'], name: string, chars: number): SpendTool {
    return { kind, tool: name, runs: 1, calls: 2, errors: 1, result_chars: chars, est_tokens: Math.floor(chars / 4) }
}

describe('spend', () => {
    it("takes idle ticks' part out of the overseer's, so the series sum to the day's total", () => {
        const costs: SpendCosts = {
            ...NONE,
            overseer: 1.5,
            idle: 0.5,
            workers: 2,
            dry_run: 0.25,
            outside: 1.25,
            total: 5,
        }
        expect(seriesCost(costs, 'idle')).toBe(0.5)
        expect(seriesCost(costs, 'overseer')).toBe(1)
        expect(seriesCost(costs, 'outside')).toBe(1.25)
        expect(SERIES.reduce((sum, s) => sum + seriesCost(costs, s.key), 0)).toBe(5)
        expect(seriesCost(NONE, 'overseer')).toBe(0)
    })

    it("tops the chart at the dearest day's total, or 0 for a window with nothing reported", () => {
        expect(chartTop([day('2026-10-07', { total: 1 }), day('2026-10-08', { total: 4.5 })])).toBe(4.5)
        expect(chartTop([day('2026-10-08', {})])).toBe(0)
        expect(chartTop([])).toBe(0)
    })

    it('says a day on hover with each series it has', () => {
        expect(
            dayHint(day('2026-10-07', { overseer: 1, idle: 0.25, reviews: 0.5, tasks: 0.75, total: 2.25 }), H24),
        ).toBe('Oct 7: $2.25, overseer $1.00 (idle ticks $0.25), reviews $0.50, tasks $0.75')
        expect(dayHint(day('2026-10-06', { workers: 1, outside: 0.5, total: 1.5 }), H24)).toBe(
            'Oct 6: $1.50, workers $1.00, outside canopy $0.50',
        )
        expect(dayHint(day('2026-10-02', {}), H24)).toBe('Oct 2: nothing reported')
        expect(dayHint(hourOf(14, { workers: 2, total: 2 }), H24)).toMatch(/^\S+ 8 14:00: \$2\.00, workers \$2\.00$/u)
        expect(dayHint(hourOf(14, { workers: 2, total: 2 }), H12)).toMatch(/^\S+ 8 2:00 PM: \$2\.00/u)
    })

    it('names a day as the axis does, whatever the zone', () => {
        expect(dayLabel(day('2026-10-01', {}), H24)).toBe('Oct 1')
        expect(dayLabel(day('2026-12-31', {}), H12)).toBe('Dec 31')
        expect(dayName({ day: '2026-10-08', start: '2026-10-07T15:00:00Z' }, H24)).toBe('Oct 8')
    })

    it('names an hour by when it starts in the browser, on the axis by its time alone, on the clock asked for', () => {
        expect(dayLabel(hourOf(9), H24)).toBe('09:00')
        expect(dayName(hourOf(9), H24)).toMatch(/^\S+ 8 09:00$/u)
        expect(dayLabel(hourOf(0), H12)).toBe('12:00 AM')
        expect(dayLabel(hourOf(14), H12)).toBe('2:00 PM')
        expect(dayName(hourOf(14), H12)).toMatch(/^\S+ 8 2:00 PM$/u)
    })

    it('names the zone after an hour in full when asked, but never on the axis', () => {
        expect(dayName(hourOf(14), { hours: '24', zone: true })).toMatch(/^\S+ 8 14:00 \S+$/u)
        expect(dayLabel(hourOf(14), { hours: '24', zone: true })).toBe('14:00')
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

    it('draws each day as a bar of its series, bottom up, the overseer less its idle ticks', () => {
        const [bar] = spendBars([day('2026-10-07', { overseer: 1, idle: 0.25, workers: 2, total: 3 })], H24)
        expect(bar?.key).toBe('2026-10-07')
        expect(bar?.label).toBe('Oct 7')
        expect([bar?.total, bar?.totalText]).toEqual([3, '$3.00'])
        expect(bar?.segments.map((s) => [s.key, s.value])).toEqual(
            SERIES.map((s) => [s.key, seriesCost({ ...NONE, overseer: 1, idle: 0.25, workers: 2, total: 3 }, s.key)]),
        )
        expect(bar?.segments.find((s) => s.key === 'overseer')?.value).toBe(0.75)
        expect(spendBars([day('2026-10-08', {})], H24)[0]?.total).toBe(0)
    })

    it('says which ended runs reported no cost, or that every one did', () => {
        expect(
            unpricedText([
                { kind: 'overseer', runs: 3, unpriced: 0 },
                { kind: 'workers', runs: 4, unpriced: 1 },
                { kind: 'chores', runs: 2, unpriced: 2 },
            ]),
        ).toBe('No cost reported: 1 of 4 worker runs, 2 of 2 chore runs.')
        expect(unpricedText([{ kind: 'workers', runs: 4, unpriced: 0 }])).toBe('Every run that ended reported a cost.')
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
            'plans',
            'chores',
            'reviews',
            'tasks',
            'dry runs',
            'outside canopy',
        ])
    })

    it("sums each model's runs over every kind, the costliest first and the unnamed last, or keeps one kind's", () => {
        const models: SpendModel[] = [
            { kind: 'overseer', model: 'a/small', runs: 4, replies: 40, cost_usd: 1, ...ALONE },
            { kind: 'overseer', model: null, runs: 2, replies: 0, cost_usd: null, ...ALONE },
            { kind: 'workers', model: 'a/big', runs: 1, replies: 9, cost_usd: 1.5, ...ALONE },
            { kind: 'workers', model: 'a/small', runs: 2, replies: 6, cost_usd: 0.75, ...ALONE },
            { kind: 'workers', model: null, runs: 3, replies: 0, cost_usd: 2, ...ALONE },
        ]
        expect(modelRows(models, undefined)).toEqual([
            { model: 'a/small', runs: 6, replies: 46, cost_usd: 1.75, ...ALONE },
            { model: 'a/big', runs: 1, replies: 9, cost_usd: 1.5, ...ALONE },
            { model: null, runs: 5, replies: 0, cost_usd: 2, ...ALONE },
        ])
        expect(modelRows(models, 'overseer').map((m) => m.model)).toEqual(['a/small', null])
        expect(modelRows(models, 'plans')).toEqual([])
    })

    it('keeps the runs canopy has yet to read apart from those read that named none, unread first', () => {
        const models: SpendModel[] = [
            { kind: 'overseer', model: null, runs: 1, replies: 0, cost_usd: 3, ...ALONE },
            { kind: 'overseer', model: null, runs: 2, replies: 0, cost_usd: 0.5, ...ALONE, unread: true },
            { kind: 'workers', model: 'a/big', runs: 1, replies: 9, cost_usd: 1.5, ...ALONE },
            { kind: 'workers', model: null, runs: 3, replies: 0, cost_usd: 1, ...ALONE, unread: true },
        ]
        const rows = modelRows(models, undefined)
        expect(rows.map((m) => [modelKey(m), m.runs, m.cost_usd])).toEqual([
            ['a/big', 1, 1.5],
            ['unread', 5, 1.5],
            ['none', 1, 3],
        ])
        // The header's share is the unread row's alone: none will never name a model.
        expect(unreadShare(rows)).toBe(0.25)
        expect(unreadShare(rows.filter((m) => !m.unread))).toBeNull()
    })

    it("gives a model's spend per run, so two models' runs compare, and the share canopy has yet to read", () => {
        const rows = [
            { model: 'a/small', runs: 6, replies: 46, cost_usd: 1.5, ...ALONE },
            { model: 'a/big', runs: 1, replies: 9, cost_usd: 0.5, ...ALONE },
            { model: null, runs: 5, replies: 0, cost_usd: 2, ...ALONE, unread: true },
        ]
        expect(rows.map((row) => perRun(row))).toEqual([0.25, 0.5, 0.4])
        expect(perRun({ model: null, runs: 2, replies: 0, cost_usd: null, ...ALONE })).toBeNull()
        expect(unreadShare(rows)).toBe(0.5)
        expect(unreadShare(rows.slice(0, 2))).toBeNull()
        expect(unreadShare([{ model: null, runs: 2, replies: 0, cost_usd: null, ...ALONE, unread: true }])).toBeNull()
    })

    it("sets a ticket's rows beside the workspace's per run, summed over every kind as their own are", () => {
        const models: SpendModel[] = [
            {
                kind: 'workers',
                model: 'a/big',
                runs: 2,
                replies: 9,
                cost_usd: 2.2,
                workspace_runs: 5,
                workspace_cost_usd: 4.5,
                unread: false,
            },
            {
                kind: 'reviews',
                model: 'a/big',
                runs: 1,
                replies: 1,
                cost_usd: 0.3,
                workspace_runs: 3,
                workspace_cost_usd: 0.75,
                unread: false,
            },
        ]
        const [summed] = modelRows(models, undefined)
        expect(summed).toMatchObject({ runs: 3, workspace_runs: 8, workspace_cost_usd: 5.25 })
        expect(models.map((m) => workspacePerRun(m))).toEqual([0.9, 0.25])
        expect(workspacePerRun({ ...ALONE })).toBeNull()
        expect(workspacePerRun({ workspace_runs: 2, workspace_cost_usd: null })).toBeNull()
    })

    it("opens By model on a ticket's workers, which all widens again, and on every kind without one", () => {
        expect(modelKind(undefined, 'ABC-1')).toBe('workers')
        expect(modelKind('all', 'ABC-1')).toBeUndefined()
        expect(modelKind('reviews', 'ABC-1')).toBe('reviews')
        expect(modelKind(undefined, undefined)).toBeUndefined()
        expect(modelKind('all', undefined)).toBeUndefined()
    })

    it('compares the models that served a ticket only when more than one did, or its override set one', () => {
        const one = [modelRow('workers', 'a/big'), modelRow('workers', null)]
        const two = [modelRow('workers', 'a/big'), modelRow('workers', 'a/small'), modelRow('workers', null)]
        expect(comparedModels(one, false)).toEqual([])
        expect(comparedModels(one, true).map((m) => m.model)).toEqual(['a/big'])
        expect(comparedModels(two, false).map((m) => m.model)).toEqual(['a/big', 'a/small'])
        expect(comparedModels([modelRow('workers', null)], true)).toEqual([])
    })

    it("sums each tool's calls over every kind, the most returned first, its tokens from the sum", () => {
        const tools = [tool('overseer', 'read', 600), tool('workers', 'bash', 500), tool('workers', 'read', 3)]
        expect(toolRows(tools, undefined)).toEqual([
            { tool: 'read', runs: 2, calls: 4, errors: 2, result_chars: 603, est_tokens: 150 },
            { tool: 'bash', runs: 1, calls: 2, errors: 1, result_chars: 500, est_tokens: 125 },
        ])
        expect(toolRows(tools, 'workers').map((t) => t.tool)).toEqual(['bash', 'read'])
    })

    it('offers the kinds with rows, in canopy spend order, and the one chosen though it has none', () => {
        const rows = [{ kind: 'reviews' as const }, { kind: 'overseer' as const }, { kind: 'reviews' as const }]
        expect(kindsOffered(rows, undefined)).toEqual(['overseer', 'reviews'])
        expect(kindsOffered(rows, 'plans')).toEqual(['overseer', 'plans', 'reviews'])
    })
})

// October 2026 a quarter gone, with a $40 budget, and what it spent and where that pace takes it.
function month(spent: number | null, projected: number | null): SpendMonth {
    return {
        month: '2026-10',
        since: '2026-10-01T00:00:00Z',
        until: '2026-11-01T00:00:00Z',
        budget_usd: 40,
        spent_usd: spent,
        elapsed: 0.25,
        projected_usd: projected,
        alerts: [50, 80, 100],
        runs_usd: spent,
        outside_usd: 0,
        sessions_read_at: null,
    }
}

describe('monthly budget', () => {
    it('is under while its pace stays within it, headed over when the pace passes it, and over once spent', () => {
        expect(budgetState(month(5, 20))).toBe('under')
        expect(budgetState(month(null, null))).toBe('under')
        expect(budgetState(month(15.76, 65.14))).toBe('headed')
        expect(budgetState(month(40, 160))).toBe('over')
    })

    it('says what it spent of the budget, and where its pace takes it', () => {
        expect(budgetText(month(15.76, 65.14))).toBe('$15.76 of $40 (39%), on pace for $65.14.')
        expect(budgetText(month(null, null))).toBe('$0.00 of $40 (0%).')
        expect(budgetPercent(month(50, null))).toBe(125)
        // Short of the budget never reads as all of it, and a float a hair under a whole point is still that point.
        expect(budgetPercent(month(39.84, null))).toBe(99)
        expect(budgetPercent({ ...month(29, null), budget_usd: 100 })).toBe(29)
        expect(budgetPercent({ ...month(0.29, null), budget_usd: 1 })).toBe(29)
    })

    it("names canopy's runs and the sessions outside canopy as of their last read, or that none counts yet", () => {
        const read = {
            ...month(15.76, null),
            runs_usd: 12.5,
            outside_usd: 3.26,
            sessions_read_at: '2026-10-08T11:55:00Z',
        }
        expect(budgetPartsText(read, H24)).toBe(
            `Canopy's runs $12.50, outside canopy $3.26, as of ${stamp('2026-10-08T11:55:00Z', H24)}.`,
        )
        expect(budgetPartsText({ ...month(null, null), runs_usd: null }, H24)).toBe(
            "Canopy's runs $0.00. Sessions outside canopy count once canopy loop has read them.",
        )
    })

    it('names each alert, and marks those short of the budget on the bar', () => {
        expect(alertsText(month(1, null))).toBe('A sink that takes loop events hears at 50%, 80%, and 100%.')
        expect(alertMarks({ ...month(1, null), alerts: [50, 100, 150] })).toEqual([50])
        expect(alertsText({ ...month(1, null), alerts: [100] })).toBe('A sink that takes loop events hears at 100%.')
    })

    it('names the month as a calendar does', () => {
        expect(monthName(month(1, null))).toBe('October 2026')
    })

    it("splits what it spent from where its pace takes it, the bar's line, which waits for a pace", () => {
        expect(budgetSpentText(month(15.76, 65.14))).toBe('$15.76 of $40 (39%)')
        expect(paceText(month(15.76, 65.14))).toBe('On pace to spend $65.14 of $40.')
        expect(paceText(month(1, null))).toBeNull()
    })

    it("labels the bar's mark with the day of the month, from how much of it has gone by", () => {
        // A quarter of October's 31 days is the middle of its 8th.
        expect(budgetDayText(month(1, null))).toBe('day 8 of 31')
        expect(budgetDayText({ ...month(1, null), elapsed: 0 })).toBe('day 1 of 31')
        expect(budgetDayText({ ...month(1, null), elapsed: 1 })).toBe('day 31 of 31')
        expect(budgetDayText({ ...month(1, null), month: '2026-02', elapsed: 0.5 })).toBe('day 15 of 28')
    })
})

// The series of `keys`, in the order the page names them.
function named(...keys: string[]) {
    return SERIES.filter((series) => keys.includes(series.key))
}

describe('the totals at a dash', () => {
    it('fold into one line, the sessions outside canopy by their own name', () => {
        expect(foldedText(named('dry_run', 'outside'), true)).toBe('No dry runs, no sessions outside canopy.')
        expect(foldedText(named('idle'), true)).toBe('No idle ticks.')
    })

    it("say the sessions outside canopy wait on the loop's read, rather than that there were none", () => {
        expect(foldedText(named('outside'), false)).toBe('Sessions outside canopy not read yet.')
    })

    it('say nothing when no total is folded', () => {
        expect(foldedText([], false)).toBe('')
    })
})

describe('By day by week', () => {
    it('is offered over 30 days alone', () => {
        expect(weeksOffered({ days: 30 })).toBe(true)
        expect(weeksOffered({ days: 7 })).toBe(false)
        expect(weeksOffered({ hours: 24 })).toBe(false)
    })

    it("sums the window's days by ISO week, each named by its Monday, a part week at either end", () => {
        // Saturday 3 October to Tuesday 13 October 2026: the end of one week, a whole one, and the start of another.
        const days = ['03', '04', '05', '06', '07', '08', '09', '10', '11', '12', '13'].map((d) =>
            day(`2026-10-${d}`, { workers: 1, total: 1 }),
        )
        const [first] = days
        if (first !== undefined) {
            first.costs = { ...NONE, overseer: 0.5, idle: 0.25, total: 0.5 }
            first.done = 2
        }
        const weeks = spendWeeks(days)
        expect(weeks.map((w) => [w.week, w.days, w.costs.total, w.done])).toEqual([
            ['2026-09-28', 2, 1.5, 2],
            ['2026-10-05', 7, 7, 0],
            ['2026-10-12', 2, 2, 0],
        ])
        // A series no day of the week reported stays unreported.
        expect(weeks[1]?.costs.overseer).toBeNull()
        expect(weekName({ week: '2026-10-05' })).toBe('week of Oct 5')

        const bars = weekBars(weeks)
        expect(bars.map((bar) => bar.label)).toEqual(['Sep 28', 'Oct 5', 'Oct 12'])
        expect(bars[0]?.hint).toBe('week of Sep 28, 2 days: $1.50, overseer $0.50 (idle ticks $0.25), workers $1.00')
        expect(bars[1]?.hint).toBe('week of Oct 5: $7.00, workers $7.00')
    })
})

describe('sessionsReadText', () => {
    it('says when the sessions were read, how the latest read ended when it found nothing, or that none was', () => {
        const at = '2026-10-08T11:55:00Z'
        const sessions: SpendSessions = {
            canopy: { sessions: 2, cost_usd: 1.5 },
            outside: { sessions: 1, cost_usd: 2 },
            directories: [{ directory: '/home/me/notes', sessions: 1, cost_usd: 2 }],
            read_at: at,
            status: 'found',
        }
        expect(sessionsReadText(sessions, H24)).toBe(`read ${stamp(at, H24)}`)
        expect(sessionsReadText({ ...sessions, status: 'failed' }, H24)).toBe(`read ${stamp(at, H24)}, last failed`)
        expect(sessionsReadText({ ...sessions, read_at: null, status: null }, H24)).toBe('never read')
    })
})

// One kind's By model row for `model`, of one run.
function modelRow(kind: SpendModel['kind'], model: string | null): SpendModel {
    return { kind, model, runs: 1, replies: 1, cost_usd: 0.1, ...ALONE }
}

describe('listedModels', () => {
    it('keeps the models a kind the runs page lists served, a plan as a worker, never the overseer alone', () => {
        const listed = listedModels([
            modelRow('overseer', 'a/tick-only'),
            modelRow('overseer', 'a/both'),
            modelRow('plans', 'a/both'),
            modelRow('reviews', 'b/review'),
            modelRow('workers', null),
        ])
        expect([...listed].toSorted()).toEqual(['a/both', 'b/review'])
    })
})
