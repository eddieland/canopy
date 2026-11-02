import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { SpendFirstCallWeek } from '@/api/types'
import { tipOf } from '@/test-utils'

import { FirstCallChart } from './first-call-chart'

afterEach(cleanup)

/** A week of the workers' own series, as the server sends it. */
function week(over: Partial<SpendFirstCallWeek>): SpendFirstCallWeek {
    return {
        kind: 'workers',
        by: 'kind',
        name: null,
        week: '2026-W41',
        runs: 2,
        first_call: 24_200,
        hit_rate: 0.85,
        new_runtime_versions: [],
        new_digests: [],
        ...over,
    }
}

const WEEKS = [
    week({ week: '2026-W38', runs: 2, first_call: 24_200, hit_rate: 0.85 }),
    week({ week: '2026-W39', runs: 1, first_call: 22_400, hit_rate: 0.57, new_digests: ['a81d2c4e9f306b17'] }),
    week({ week: '2026-W40', runs: 3, first_call: 22_400, hit_rate: null, new_runtime_versions: ['1.0.104'] }),
]

describe('FirstCallChart', () => {
    it('draws a bar per week with its rate, hidden from a screen reader, and marks the weeks that changed', () => {
        render(<FirstCallChart weeks={WEEKS} fill="bg-spend-workers" />)
        const chart = screen.getByTestId('first-call-chart')
        expect(chart.getAttribute('aria-hidden')).toBe('true')
        expect(within(chart).getAllByTestId(/^first-call-bar-/u)).toHaveLength(3)
        expect(screen.getByTestId('first-call-bar-2026-W39').textContent).toBe('57%')
        expect(screen.getByTestId('first-call-bar-2026-W39').getAttribute('title')).toBe(
            'Week of Sep 21: 57% from the cache, a median 22.4k sent, 1 run; new snapshot a81d2c4e9f306b17',
        )
        // A week with no cache read recorded says so with a dash, not as nothing read.
        expect(screen.getByTestId('first-call-bar-2026-W40').textContent).toBe('–')
        expect(within(chart).getAllByTestId('first-call-marker')).toHaveLength(2)
        expect(within(screen.getByTestId('first-call-bar-2026-W38')).queryByTestId('first-call-marker')).toBeNull()
        expect(within(chart).getByText('Sep 14')).toBeDefined()
    })

    it('names what each marked week used first, in a list a screen reader reads', () => {
        render(<FirstCallChart weeks={WEEKS} fill="bg-spend-workers" />)
        const changes = screen.getByRole('list', { name: 'What changed' })
        expect(
            within(changes)
                .getAllByRole('listitem')
                .map((li) => li.textContent),
        ).toEqual(['Week of Sep 21: snapshot a81d2c4e9f306b17', 'Week of Sep 28: runtime 1.0.104'])
    })

    it("counts a week's several new snapshots, each one named in the count's tip", () => {
        const several = week({ week: '2026-W41', new_digests: ['a81d2c4e', 'b92e3d5f'] })
        render(<FirstCallChart weeks={[...WEEKS, several]} fill="bg-spend-workers" />)
        const changes = screen.getByRole('list', { name: 'What changed' })
        const item = within(changes).getAllByRole('listitem').at(-1)
        expect(item?.textContent).toBe('Week of Oct 5: 2 snapshots')
        expect(tipOf(screen.getByText('2 snapshots'))).toContain('a81d2c4e\nb92e3d5f')
    })

    it('lists no changes when no week made one', () => {
        render(<FirstCallChart weeks={[WEEKS[0] ?? week({})]} fill="bg-spend-workers" />)
        expect(screen.queryByRole('list', { name: 'What changed' })).toBeNull()
    })

    it('holds the numbers in a table, the newest week first, the median first call among them', () => {
        render(<FirstCallChart weeks={WEEKS} fill="bg-spend-workers" />)
        const table = screen.getByRole('table')
        expect(
            within(table)
                .getAllByRole('columnheader')
                .map((th) => th.textContent),
        ).toEqual(['week of', 'runs', 'first call', 'from cache'])
        const rows = within(table).getAllByRole('row').slice(1)
        const cells = rows.map((row) =>
            [within(row).getByRole('rowheader'), ...within(row).getAllByRole('cell')].map((c) => c.textContent),
        )
        expect(cells).toEqual([
            ['Sep 28', '3', '22.4k', '–'],
            ['Sep 21', '1', '22.4k', '57%'],
            ['Sep 14', '2', '24.2k', '85%'],
        ])
        expect(tipOf(within(table).getByText('Sep 28'))).toBe('2026-W40')
    })
})
