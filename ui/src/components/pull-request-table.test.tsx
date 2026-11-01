import { QueryClient } from '@tanstack/react-query'
import { cleanup, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { renderRouted, tipOf } from '@/test-utils'

import { PullRequestTable } from './pull-request-table'
import type { PullRequestColumn, PullRequestRow } from './pull-request-table'

afterEach(() => {
    cleanup()
})

interface Row extends PullRequestRow {
    runs: number
}

const COLUMNS: PullRequestColumn<Row>[] = [
    { key: 'runs', label: 'runs', hint: 'Its runs', cell: (row) => row.runs, title: (row) => `${row.runs} runs` },
]

describe('PullRequestTable', () => {
    it('lists each PR with its phase and ticket, then its figures, under named heads', async () => {
        const rows: Row[] = [
            { url: 'https://github.com/acme/web/pull/88', ticket_key: 'ABC-099', phase: 'ci_red', runs: 3 },
            { url: 'https://github.com/acme/api/pull/12', ticket_key: null, phase: null, runs: 1 },
        ]
        const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
        await renderRouted(<PullRequestTable rows={rows} columns={COLUMNS} label="By PR" testId="x" />, { client })
        const table = screen.getByTestId('x-pull-request-table')
        expect(
            within(table)
                .getAllByRole('columnheader')
                .map((th) => th.textContent),
        ).toEqual(['pull request', 'ticket', 'runs'])
        const [first, second] = within(table).getAllByTestId('x-pull-request')
        expect(first?.textContent).toContain('ci red')
        expect(within(first as HTMLElement).getByRole('link', { name: 'ABC-099' })).toBeTruthy()
        expect(tipOf(within(second as HTMLElement).getByText('1'))).toBe('1 runs')
        expect(within(second as HTMLElement).queryByRole('link', { name: /ABC/u })).toBeNull()
    })
})
