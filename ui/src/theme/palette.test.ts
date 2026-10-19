import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { breakStorage, otherTab } from '@/test-utils'

// The setting is read when the module loads, so each test imports a fresh copy.
function load() {
    vi.resetModules()
    return import('./palette')
}

const root = document.documentElement

beforeEach(() => {
    localStorage.clear()
    delete root.dataset.lightPalette
    delete root.dataset.darkPalette
})

describe('parsePalettes', () => {
    it.each([
        { raw: null, palettes: { light: 'indigo', dark: 'indigo' } },
        { raw: '{"light":"solarized"}', palettes: { light: 'solarized', dark: 'indigo' } },
        { raw: '{"light":"off-white","dark":"grey"}', palettes: { light: 'off-white', dark: 'grey' } },
        { raw: '{"light":"grey","dark":"solarized"}', palettes: { light: 'indigo', dark: 'indigo' } },
        { raw: '{"dark":"mauve"}', palettes: { light: 'indigo', dark: 'indigo' } },
        { raw: '"grey"', palettes: { light: 'indigo', dark: 'indigo' } },
        { raw: 'null', palettes: { light: 'indigo', dark: 'indigo' } },
        { raw: 'not json', palettes: { light: 'indigo', dark: 'indigo' } },
    ])('reads $raw as $palettes', async ({ raw, palettes }) => {
        const { parsePalettes } = await load()
        expect(parsePalettes(raw)).toEqual(palettes)
    })
})

describe('palettes', () => {
    it('stores one theme, keeps the other, and puts both on <html>', async () => {
        const palette = await load()
        palette.setPalette('dark', 'grey')
        expect(JSON.parse(localStorage.getItem(palette.STORAGE_KEY) ?? '')).toEqual({ light: 'indigo', dark: 'grey' })
        expect(root.dataset.darkPalette).toBe('grey')
        expect(root.dataset.lightPalette).toBe('indigo')
    })

    it('still applies where storage is unavailable', async () => {
        breakStorage()
        const palette = await load()
        palette.setPalette('light', 'off-white')
        expect(root.dataset.lightPalette).toBe('off-white')
    })

    it("follows another tab's pick, on <html> too", async () => {
        const palette = await load()
        const { result } = renderHook(() => palette.usePalettes())
        expect(result.current).toEqual({ light: 'indigo', dark: 'indigo' })

        act(() => otherTab(palette.STORAGE_KEY, '{"light":"solarized","dark":"indigo"}'))

        expect(result.current).toEqual({ light: 'solarized', dark: 'indigo' })
        expect(root.dataset.lightPalette).toBe('solarized')
    })
})
