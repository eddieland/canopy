import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { setListOrder, STORAGE_KEY } from '@/lib/list-order'
import { otherTab } from '@/test-utils'

import { OrderToggle } from './order-toggle'

afterEach(() => {
    cleanup()
    setListOrder('ticks', 'newest')
    setListOrder('tickets', 'newest')
    localStorage.clear()
})

describe('OrderToggle', () => {
    it('says which end comes first, flips to the other on a click, and keeps the choice', () => {
        render(<OrderToggle list="ticks" />)
        fireEvent.click(screen.getByRole('button', { name: 'newest first: show oldest first' }))
        expect(screen.getByRole('button', { name: 'oldest first: show newest first' }).textContent).toBe('oldest first')
        expect(localStorage.getItem(STORAGE_KEY)).toBe('{"ticks":"oldest"}')
    })

    it('says a list by activity runs recently updated first, or least', () => {
        render(<OrderToggle list="tickets" />)
        fireEvent.click(screen.getByRole('button', { name: 'recently updated: show least recently updated' }))
        expect(screen.getByRole('button', { name: 'least recently updated: show recently updated' })).toBeDefined()
    })

    it('follows a flip made in another tab', () => {
        render(<OrderToggle list="ticks" />)
        act(() => {
            otherTab(STORAGE_KEY, '{"ticks":"oldest"}')
        })
        expect(screen.getByRole('button', { name: 'oldest first: show newest first' })).toBeDefined()
    })
})
