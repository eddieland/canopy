import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { CellBar } from './cell-bar'

afterEach(() => {
    cleanup()
})

describe('CellBar', () => {
    it('shows its figure, with the bar hidden from a screen reader', () => {
        render(<CellBar percent={25}>$1.00</CellBar>)
        expect(screen.getByText('$1.00')).toBeTruthy()
        expect(screen.getByTestId('cell-bar').getAttribute('aria-hidden')).toBe('true')
    })

    it('draws its share of the largest, never past the cell', () => {
        render(
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
})
