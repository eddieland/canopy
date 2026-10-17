import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { STORAGE_KEY } from '@/theme/store'
import { stubSystemTheme } from '@/test-utils'

import { ThemeToggle } from './theme-toggle'

beforeEach(() => {
    localStorage.clear()
})

afterEach(() => {
    cleanup()
    localStorage.clear()
    const root = document.documentElement
    root.className = ''
    delete root.dataset['theme']
    root.style.colorScheme = ''
})

describe('ThemeToggle', () => {
    it('offers the theme the system does not use, and switches to it for good', () => {
        stubSystemTheme(true)
        render(<ThemeToggle />)

        fireEvent.click(screen.getByRole('button', { name: 'Switch to light theme' }))
        expect(document.documentElement.classList.contains('dark')).toBe(false)
        expect(localStorage.getItem(STORAGE_KEY)).toBe('light')

        fireEvent.click(screen.getByRole('button', { name: 'Switch to dark theme' }))
        expect(document.documentElement.classList.contains('dark')).toBe(true)
        expect(localStorage.getItem(STORAGE_KEY)).toBe('dark')
    })

    it('follows the system while no theme is chosen', () => {
        const system = stubSystemTheme(false)
        render(<ThemeToggle />)
        expect(screen.getByRole('button', { name: 'Switch to dark theme' })).toBeDefined()

        act(() => system.set(true))
        expect(screen.getByRole('button', { name: 'Switch to light theme' })).toBeDefined()
    })
})
