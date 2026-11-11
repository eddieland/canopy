import { describe, expect, it } from 'vitest'

import type { ConnectorsDay, ConnectorsSource, ConnectorsSourceRuns } from '@/api/types'
import type { Clock } from '@/lib/clock'

import {
    connectorBars,
    connectorDayHint,
    connectorSeries,
    connectorsFigures,
    connectorsLine,
    connectorsWindow,
    freshnessText,
    linesText,
    previousConnectorsFigures,
    retentionText,
    shortShareText,
    shortSum,
} from './connectors'

const H24: Clock = { hours: '24', zone: false }

function runs(name: string, counts: Partial<ConnectorsSourceRuns> = {}): ConnectorsSourceRuns {
    return {
        source: name,
        kind: 'tracker',
        runs: 10,
        ticks: 2,
        polls: 8,
        ok: 10,
        partial: 0,
        failed: 0,
        median_minutes: 0.2,
        p90_minutes: 0.3,
        longest_minutes: 0.4,
        limit_minutes: 2,
        recorded: {},
        refused: {},
        ...counts,
    }
}

function source(name: string, stale: boolean): ConnectorsSource {
    return {
        name,
        kind: 'tracker',
        run_id: 1,
        tick_id: null,
        status: 'ok',
        ended_at: '2026-10-08T11:30:00Z',
        missed: null,
        oldest_at: null,
        never: 0,
        stale,
        through: null,
    }
}

function day(name: string, short: number[]): ConnectorsDay {
    return { day: name, start: `${name}T00:00:00Z`, short }
}

describe('connectors', () => {
    it('offers the week and 30 days, as the health page does', () => {
        expect(connectorsWindow({ days: '30' })).toEqual({ days: 30 })
        expect(connectorsWindow({ days: 7 })).toEqual({ days: 7 })
        expect(connectorsWindow({ days: '14' })).toBeUndefined()
        expect(connectorsWindow({})).toBeUndefined()
    })

    it("says the window's state, then each stale source by name", () => {
        expect(
            connectorsLine({
                days: 7,
                runs: [runs('jira', { ok: 8, partial: 2 }), runs('github', { ok: 9, failed: 1 })],
                sources: [source('jira', true), source('github', false)],
            }),
        ).toBe('3 of 20 runs read less than asked over 7 days · jira stale')
        expect(connectorsLine({ days: 30, runs: [], sources: [source('jira', false)] })).toBe(
            'no source ran over 30 days',
        )
        // A week of polls runs to thousands, grouped as they are read.
        expect(connectorsLine({ days: 7, runs: [runs('jira', { runs: 4210, partial: 6 })], sources: [] })).toBe(
            '6 of 4,210 runs read less than asked over 7 days',
        )
    })

    it("sums the window's figures over every source, and reads the window before's alike", () => {
        const found = connectorsFigures({
            runs: [runs('jira', { partial: 1, refused: { comment: 2 } }), runs('github', { failed: 1 })],
        })
        expect(found).toEqual({ runs: 20, short: 2, rate: 0.1, refused: 2 })
        expect(connectorsFigures({ runs: [] }).rate).toBeNull()
        expect(previousConnectorsFigures({ since: '', until: '', runs: 4, short: 1, refused: 0 })).toEqual({
            runs: 4,
            short: 1,
            rate: 0.25,
            refused: 0,
        })
    })

    it('writes a share of runs that read less than asked, keeping a few in many apart from none', () => {
        expect(shortShareText(runs('jira', { runs: 200, partial: 1 }))).toBe('<1%')
        expect(shortShareText(runs('jira', { runs: 10, partial: 1, failed: 1 }))).toBe('20%')
        expect(shortShareText(runs('jira'))).toBe('0%')
        expect(shortShareText(runs('jira', { runs: 0 }))).toBe('–')
    })

    it('writes lines by kind, the most first', () => {
        expect(linesText({ comment: 195, ticket: 1164, pr: 0 })).toBe('1164 ticket, 195 comment')
        expect(linesText({ b: 2, a: 2 })).toBe('2 a, 2 b')
        expect(linesText({})).toBe('–')
    })

    it('draws a series per source in its place, and each day by source with a hint naming them', () => {
        const series = connectorSeries([runs('jira'), runs('github')])
        expect(series.map((s) => [s.key, s.label, s.fill])).toEqual([
            ['source-0', 'jira', 'bg-check-1'],
            ['source-1', 'github', 'bg-check-2'],
        ])
        const days = [day('2026-10-07', [1, 1]), day('2026-10-08', [0, 0])]
        expect(shortSum(days[0] as ConnectorsDay)).toBe(2)
        expect(connectorDayHint(days[0] as ConnectorsDay, series, H24)).toBe(
            'Oct 7: 2 read less than asked, jira 1, github 1',
        )
        expect(connectorDayHint(days[1] as ConnectorsDay, series, H24)).toBe('Oct 8: 0 read less than asked')
        const [bar] = connectorBars(days, series, H24)
        expect(bar?.total).toBe(2)
        expect(bar?.segments.map((s) => s.value)).toEqual([1, 1])
    })

    it('says how fresh a source reads beside its oldest observation', () => {
        const fresh = source('jira', false)
        expect(freshnessText({ ...fresh, oldest_at: '2026-10-08T11:31:00Z' })).toBe('')
        expect(freshnessText({ ...fresh, never: 2 })).toBe('2 never observed')
        expect(freshnessText(fresh)).toBe('nothing observed')
        expect(freshnessText({ ...fresh, through: 41, oldest_at: '2026-10-08T11:00:00Z' })).toBe(
            'feed through change 41',
        )
        expect(freshnessText({ ...fresh, through: 0 })).toBe('feed through change 0, never read to its end')
    })

    it('says how long the journal keeps a run, and when the window reaches past it', () => {
        expect(retentionText({ journal_days: 90, days: 30 })).toBe(
            "The journal keeps a run 90 days (retention.journal_days), each source's newest whatever its age.",
        )
        expect(retentionText({ journal_days: 7, days: 30 })).toContain('so this window is not whole.')
        expect(retentionText({ journal_days: 0, days: 30 })).toBe(
            'retention.journal_days is 0, so the journal keeps every run.',
        )
    })
})
