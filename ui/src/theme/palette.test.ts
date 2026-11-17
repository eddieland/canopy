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
        { raw: null, palettes: { light: 'lavender', dark: 'indigo' } },
        { raw: '{"light":"solarized"}', palettes: { light: 'solarized', dark: 'indigo' } },
        { raw: '{"light":"off-white","dark":"grey"}', palettes: { light: 'off-white', dark: 'grey' } },
        { raw: '{"light":"grey","dark":"nord"}', palettes: { light: 'lavender', dark: 'indigo' } },
        { raw: '{"dark":"mauve"}', palettes: { light: 'lavender', dark: 'indigo' } },
        { raw: '"grey"', palettes: { light: 'lavender', dark: 'indigo' } },
        { raw: 'null', palettes: { light: 'lavender', dark: 'indigo' } },
        { raw: 'not json', palettes: { light: 'lavender', dark: 'indigo' } },
    ])('reads $raw as $palettes', async ({ raw, palettes }) => {
        const { parsePalettes } = await load()
        expect(parsePalettes(raw)).toEqual(palettes)
    })
})

describe('palettes', () => {
    it('stores one theme, keeps the other, and puts both on <html>', async () => {
        const palette = await load()
        palette.setPalette('dark', 'grey')
        expect(JSON.parse(localStorage.getItem(palette.STORAGE_KEY) ?? '')).toEqual({ light: 'lavender', dark: 'grey' })
        expect(root.dataset.darkPalette).toBe('grey')
        expect(root.dataset.lightPalette).toBe('lavender')
    })

    it("keeps the other theme's pick from another tab this one has not heard of yet", async () => {
        const palette = await load()
        const { result } = renderHook(() => palette.usePalettes())
        // Picked in another tab, its `storage` event not yet delivered here.
        localStorage.setItem(palette.STORAGE_KEY, '{"light":"lavender","dark":"plum"}')

        act(() => palette.setPalette('light', 'sage'))

        expect(JSON.parse(localStorage.getItem(palette.STORAGE_KEY) ?? '')).toEqual({ light: 'sage', dark: 'plum' })
        expect(result.current).toEqual({ light: 'sage', dark: 'plum' })
        expect(root.dataset.darkPalette).toBe('plum')
    })

    it('keeps a palette a newer build stored, which this one does not know, as stored', async () => {
        localStorage.setItem('canopy-palette', '{"light":"lavender","dark":"a-newer-palette"}')
        const palette = await load()
        expect(palette.getPalettes().dark).toBe('indigo')

        palette.setPalette('light', 'nord')

        expect(JSON.parse(localStorage.getItem(palette.STORAGE_KEY) ?? '')).toEqual({
            light: 'nord',
            dark: 'a-newer-palette',
        })
        expect(root.dataset.darkPalette).toBe('indigo')
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
        expect(result.current).toEqual({ light: 'lavender', dark: 'indigo' })

        act(() => otherTab(palette.STORAGE_KEY, '{"light":"solarized","dark":"indigo"}'))

        expect(result.current).toEqual({ light: 'solarized', dark: 'indigo' })
        expect(root.dataset.lightPalette).toBe('solarized')
    })
})
