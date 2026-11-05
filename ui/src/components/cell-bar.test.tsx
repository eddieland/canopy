import { cleanup, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it } from 'vitest'

import { CellBar, CellBarHead } from './cell-bar'

afterEach(() => {
    cleanup()
})

/** Renders `children` as the cells of a table's one row, under a head row of `head`. */
function renderRow(children: ReactNode, head?: ReactNode) {
    return render(
        <table>
            {head !== undefined && (
                <thead>
                    <tr>{head}</tr>
                </thead>
            )}
            <tbody>
                <tr>{children}</tr>
            </tbody>
        </table>,
    )
}

describe('CellBar', () => {
    it('shows its figure in a cell of its own, with the bar hidden from a screen reader', () => {
        renderRow(<CellBar percent={25}>$1.00</CellBar>)
        expect(screen.getByRole('cell', { name: '$1.00' })).toBeTruthy()
        expect(screen.getByTestId('cell-bar').closest('td')?.getAttribute('aria-hidden')).toBe('true')
    })

    it('draws its share of the largest, never past the cell', () => {
        renderRow(
            <>
                <CellBar percent={25}>a</CellBar>
                <CellBar percent={140}>b</CellBar>
                <CellBar percent={-3}>c</CellBar>
            </>,
        )
        const widths = screen
            .getAllByTestId('cell-bar')
            .map((bar) => (bar.firstElementChild as HTMLElement | null)?.style.width)
        expect(widths).toEqual(['25%', '100%', '0%'])
    })

    it('heads its column with as many cells as a row has', () => {
        renderRow(<CellBar percent={50}>$2.00</CellBar>, <CellBarHead>spent</CellBarHead>)
        const [head, body] = screen.getAllByRole('row')
        expect(screen.getByRole('columnheader', { name: 'spent' })).toBeTruthy()
        expect(head?.children.length).toBe(body?.children.length)
    })
})
