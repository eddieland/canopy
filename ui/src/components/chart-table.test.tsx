import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { ChartTable } from './chart-table'

afterEach(() => {
    cleanup()
})

function table() {
    return (
        <ChartTable what="7 days" label="Spend by day">
            <table>
                <tbody>
                    <tr>
                        <th scope="row">Oct 7</th>
                        <td>$1.00</td>
                    </tr>
                </tbody>
            </table>
        </ChartTable>
    )
}

describe('ChartTable', () => {
    it('arrives folded, the table still there for a screen reader, with no region to stop on', () => {
        render(table())
        expect(screen.getByRole('button', { name: 'Show 7 days as a table' }).getAttribute('aria-expanded')).toBe(
            'false',
        )
        expect(screen.getByRole('rowheader', { name: 'Oct 7' })).toBeTruthy()
        expect(screen.queryByRole('region', { name: 'Spend by day' })).toBeNull()
    })

    it('opens the table in its scrolling region, once', () => {
        render(table())
        fireEvent.click(screen.getByRole('button', { name: 'Show 7 days as a table' }))
        expect(screen.getByRole('button', { name: 'Hide 7 days as a table' }).getAttribute('aria-expanded')).toBe(
            'true',
        )
        expect(screen.getByRole('region', { name: 'Spend by day' })).toBeTruthy()
        expect(screen.getAllByRole('rowheader', { name: 'Oct 7' })).toHaveLength(1)
    })
})
