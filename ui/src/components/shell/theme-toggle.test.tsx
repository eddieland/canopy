import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { renderRouted, stubSystemTheme } from '@/test-utils'
import { STORAGE_KEY as PALETTE_KEY } from '@/theme/palette'
import { STORAGE_KEY } from '@/theme/store'

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
    delete root.dataset['lightPalette']
    delete root.dataset['darkPalette']
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

    it("offers the shown theme's palettes on hover, and switches to one, leaving the other theme's alone", async () => {
        stubSystemTheme(true)
        await renderRouted(<ThemeToggle />)
        act(() => {
            screen.getByTestId('theme-toggle').focus()
        })
        const card = await waitFor(() => screen.getByTestId('palette-card'))
        const palettes = within(card).getByRole('radiogroup', { name: 'Dark palette' })
        expect(within(palettes).getByRole('radio', { name: 'Indigo' }).getAttribute('aria-checked')).toBe('true')

        fireEvent.click(within(palettes).getByRole('radio', { name: 'Plum' }))
        expect(document.documentElement.dataset['darkPalette']).toBe('plum')
        expect(document.documentElement.dataset['lightPalette']).toBe('lavender')
        expect(JSON.parse(localStorage.getItem(PALETTE_KEY) ?? 'null')).toStrictEqual({
            light: 'lavender',
            dark: 'plum',
        })
        expect(within(palettes).getByRole('radio', { name: 'Plum' }).getAttribute('aria-checked')).toBe('true')
        expect(card.textContent).toContain("The light theme's are in Settings.")
        expect(within(card).getByRole('link', { name: 'Settings' })).toBeDefined()
    })

    it("follows the theme: once flipped, the card offers the other theme's palettes", async () => {
        stubSystemTheme(false)
        await renderRouted(<ThemeToggle />)
        const toggle = screen.getByTestId('theme-toggle')
        act(() => {
            toggle.focus()
        })
        const card = await waitFor(() => screen.getByTestId('palette-card'))
        expect(within(card).getByRole('radiogroup', { name: 'Light palette' })).toBeDefined()

        fireEvent.click(toggle)
        expect(within(card).getByRole('radiogroup', { name: 'Dark palette' })).toBeDefined()
    })
})
