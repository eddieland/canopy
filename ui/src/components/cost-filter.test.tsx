import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { CostBound } from '@/lib/sessions'

import { CostFilter } from './cost-filter'

afterEach(cleanup)

function amount() {
    return screen.getByRole<HTMLInputElement>('textbox', { name: 'Cost in dollars' })
}

describe('CostFilter', () => {
    it('opens on at least, with no amount, and filters by each amount typed', () => {
        const onFilter = vi.fn<(bound: CostBound | undefined) => void>()
        render(<CostFilter bound={undefined} onFilter={onFilter} />)
        expect(screen.getByRole('radio', { name: 'at least' }).getAttribute('aria-checked')).toBe('true')
        expect(amount().value).toBe('')

        fireEvent.change(amount(), { target: { value: '1.5' } })
        expect(onFilter).toHaveBeenLastCalledWith({ op: 'gte', usd: 1.5 })
    })

    it('keeps the amount when another comparison is picked, and one always stays picked', () => {
        const onFilter = vi.fn<(bound: CostBound | undefined) => void>()
        render(<CostFilter bound={{ op: 'gte', usd: 2 }} onFilter={onFilter} />)
        expect(amount().value).toBe('2')

        fireEvent.click(screen.getByRole('radio', { name: 'less than' }))
        expect(onFilter).toHaveBeenLastCalledWith({ op: 'lt', usd: 2 })
        expect(screen.getByRole('radio', { name: 'less than' }).getAttribute('aria-checked')).toBe('true')

        // Pressing the one that is on leaves it on.
        onFilter.mockClear()
        fireEvent.click(screen.getByRole('radio', { name: 'less than' }))
        expect(onFilter).not.toHaveBeenCalled()
        expect(screen.getByRole('radio', { name: 'less than' }).getAttribute('aria-checked')).toBe('true')
    })

    it('filters nothing while no amount is typed, though a comparison is picked', () => {
        const onFilter = vi.fn<(bound: CostBound | undefined) => void>()
        render(<CostFilter bound={undefined} onFilter={onFilter} />)
        fireEvent.click(screen.getByRole('radio', { name: 'at most' }))
        expect(onFilter).toHaveBeenLastCalledWith(undefined)

        fireEvent.change(amount(), { target: { value: '3' } })
        expect(onFilter).toHaveBeenLastCalledWith({ op: 'lte', usd: 3 })
    })

    it('keeps the digits of what is pasted, and its clear button empties it', () => {
        const onFilter = vi.fn<(bound: CostBound | undefined) => void>()
        render(<CostFilter bound={{ op: 'gt', usd: 1 }} onFilter={onFilter} />)
        fireEvent.change(amount(), { target: { value: '$1,200.50' } })
        expect(amount().value).toBe('1200.50')
        expect(onFilter).toHaveBeenLastCalledWith({ op: 'gt', usd: 1200.5 })

        fireEvent.change(amount(), { target: { value: 'lots' } })
        expect(amount().value).toBe('')
        expect(onFilter).toHaveBeenLastCalledWith(undefined)

        fireEvent.change(amount(), { target: { value: '2' } })
        fireEvent.click(screen.getByRole('button', { name: 'Clear the cost' }))
        expect(amount().value).toBe('')
        expect(screen.queryByRole('button', { name: 'Clear the cost' })).toBeNull()
    })

    it('shows the bound the address changes to', () => {
        const ignored = vi.fn<(bound: CostBound | undefined) => void>()
        const { rerender } = render(<CostFilter bound={{ op: 'gte', usd: 5 }} onFilter={ignored} />)
        rerender(<CostFilter bound={{ op: 'lt', usd: 0.5 }} onFilter={ignored} />)
        expect(amount().value).toBe('0.5')
        expect(screen.getByRole('radio', { name: 'less than' }).getAttribute('aria-checked')).toBe('true')

        rerender(<CostFilter bound={undefined} onFilter={ignored} />)
        expect(amount().value).toBe('')
        expect(screen.getByRole('radio', { name: 'less than' }).getAttribute('aria-checked')).toBe('true')
    })
})
