import { QueryClient } from '@tanstack/react-query'
import { cleanup, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { renderRouted, tipOf } from '@/test-utils'

import { ReportTable } from './report-table'
import type { ReportColumn, ReportGroup } from './report-table'

afterEach(() => {
    cleanup()
})

interface Row {
    name: string
    note: string
    runs: number
    cost: string
    share: number
}

const COLUMNS: ReportColumn<Row>[] = [
    { key: 'name', kind: 'name', label: 'kind', cell: (row) => row.name },
    { key: 'note', kind: 'free', label: 'note', cell: (row) => row.note },
    { key: 'runs', kind: 'figure', label: 'runs', hint: 'Its runs', cell: (row) => row.runs, tip: (r) => `${r.runs}` },
    { key: 'cost', kind: 'bar', label: 'spent', cell: (row) => row.cost, bar: (row) => row.share },
]

const ROWS: Row[] = [
    { name: 'workers', note: 'the most', runs: 12, cost: '$1,234.56', share: 100 },
    { name: 'plans', note: 'fewer', runs: 3, cost: '$0.42', share: 4 },
]

async function renderTable() {
    const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
    await renderRouted(
        <ReportTable
            rows={ROWS}
            columns={COLUMNS}
            rowKey={(r) => r.name}
            label="By kind"
            testId="t"
            rowTestId="t-row"
        />,
        { client },
    )
    return screen.getByTestId('t')
}

describe('ReportTable', () => {
    it('heads each column, and makes the first column each row head', async () => {
        const table = await renderTable()
        expect(
            within(table)
                .getAllByRole('columnheader')
                .map((th) => th.textContent),
        ).toEqual(['kind', 'note', 'runs', 'spent'])
        expect(
            within(table)
                .getAllByRole('rowheader')
                .map((th) => th.textContent),
        ).toEqual(['workers', 'plans'])
    })

    it('reads a row as its cells, a bar hidden from a screen reader beside its figure', async () => {
        const table = await renderTable()
        const [first] = within(table).getAllByTestId('t-row')
        expect(
            within(first as HTMLElement)
                .getAllByRole('cell')
                .map((td) => td.textContent),
        ).toEqual(['the most', '12', '$1,234.56'])
        expect(
            within(first as HTMLElement)
                .getByTestId('cell-bar')
                .closest('td')
                ?.getAttribute('aria-hidden'),
        ).toBe('true')
    })

    it('gives a head row as many cells as a row has, so the columns line up', async () => {
        const table = await renderTable()
        const [head, row] = within(table).getAllByRole('row', { hidden: true })
        expect(head?.children.length).toBe(row?.children.length)
    })

    it("puts a cell's tip on it", async () => {
        const table = await renderTable()
        expect(tipOf(within(table).getByText('3'))).toBe('3')
    })

    it("heads each group's rows, by a line across the table or by a row of its own figures", async () => {
        const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
        const kinds: Row = { name: 'kinds', note: '', runs: 15, cost: '$9.00', share: 50 }
        const tasks: Row = { name: 'tasks', note: '', runs: 3, cost: 'two chips', share: 0 }
        const groups: ReportGroup<Row>[] = [
            { key: 'a', head: 'repo a', rows: ROWS, testId: 'group' },
            { key: 'b', headRow: kinds, rows: [tasks], testId: 'group' },
        ]
        const across: ReportColumn<Row> = {
            key: 'cost',
            kind: 'bar',
            label: 'spent',
            cell: (row) => row.cost,
            bar: (row) => row.share,
            across: (row) => row.name === 'tasks',
        }
        const columns = [...COLUMNS.slice(0, -1), across]
        await renderRouted(
            <ReportTable groups={groups} columns={columns} rowKey={(r) => r.name} label="By kind" testId="t" />,
            { client },
        )
        const [first, second] = within(screen.getByTestId('t')).getAllByTestId('group')
        // A line across: one cell over every column, a bar's two among them.
        const line = within(first as HTMLElement).getByRole('rowheader', { name: 'repo a' })
        expect([line.getAttribute('scope'), line.getAttribute('colspan')]).toEqual(['rowgroup', '5'])
        // A row of its own: its first cell heads the group, its bar beside its figure; a row under it lays its words
        // across the figure's cell and the bar's.
        const [head, member] = within(second as HTMLElement).getAllByRole('row', { hidden: true })
        const name = within(head as HTMLElement).getByRole('rowheader', { name: 'kinds' })
        expect(name.getAttribute('scope')).toBe('rowgroup')
        expect(within(head as HTMLElement).getByTestId('cell-bar')).toBeTruthy()
        expect(within(member as HTMLElement).queryByTestId('cell-bar')).toBeNull()
        expect(
            within(member as HTMLElement)
                .getByText('two chips')
                .closest('td')
                ?.getAttribute('colspan'),
        ).toBe('2')
    })
})
