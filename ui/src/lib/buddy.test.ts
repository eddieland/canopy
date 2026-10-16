import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { breakStorage, otherTab, otherTabClears } from '@/test-utils'

import { ANYWHERE, DEFAULT, parseBuddy, TIPS, tipFor } from './buddy'
import type { View } from './buddy'

const DAY = 86_400_000

// The setting is read when the module loads, so each test loads a fresh copy.
function load() {
    vi.resetModules()
    return import('./buddy')
}

describe('parseBuddy', () => {
    it('is off unless turned on', () => {
        expect(DEFAULT).toBe('off')
        expect(parseBuddy(null)).toBe('off')
        expect(parseBuddy('on')).toBe('on')
        expect(parseBuddy('off')).toBe('off')
        expect(parseBuddy('maybe')).toBe('off')
    })
})

describe('TIPS', () => {
    it('has several tips of its own for every view', () => {
        // The type check holds every route to a list (src/components/shell/buddy.tsx); this holds each to a few.
        for (const tips of Object.values(TIPS)) {
            expect(tips.length).toBeGreaterThanOrEqual(5)
        }
    })

    it('never says the same thing twice, on any page', () => {
        const all = [...Object.values(TIPS).flat(), ...ANYWHERE]
        expect(new Set(all).size).toBe(all.length)
    })

    it('never follows a voice with itself in a list, the last round to the first', () => {
        for (const tips of [...Object.values(TIPS), ANYWHERE]) {
            const voices = tips.map((tip) => tip.split(' ').slice(0, 2).join(' '))
            for (const [n, voice] of voices.entries()) {
                expect(voice).not.toBe(voices[(n + 1) % voices.length])
            }
        }
    })

    it('keeps every tip short enough for the bubble', () => {
        // A longer tip makes the bubble taller, which the rail's slot must hold whole (src/components/shell/buddy.tsx).
        for (const tip of [...Object.values(TIPS).flat(), ...ANYWHERE]) {
            expect(tip.length).toBeLessThanOrEqual(100)
        }
    })

    it('never opens a line with "Tip:", which is for the ticker\'s real tips', () => {
        for (const tip of [...Object.values(TIPS).flat(), ...ANYWHERE]) {
            expect(tip).not.toMatch(/^Tip:/u)
        }
    })
})

describe('tipFor', () => {
    it("draws from the view's tips and the ones for anywhere", () => {
        const length = TIPS['/chores/$name'].length + ANYWHERE.length
        const tips = new Set(Array.from({ length }, (_, n) => tipFor('/chores/$name', n, 0)))
        expect(tips).toEqual(new Set([...TIPS['/chores/$name'], ...ANYWHERE]))
    })

    it('draws only from the ones for anywhere off every view', () => {
        expect(ANYWHERE).toContain(tipFor(undefined, 0, 0))
    })

    it("opens on the view's own tips, then the ones for anywhere", () => {
        for (let day = 0; day < 12; day += 1) {
            const tips = Array.from({ length: TIPS['/runs/$id'].length + ANYWHERE.length }, (_, n) =>
                tipFor('/runs/$id', n, day * DAY),
            )
            expect(new Set(tips.slice(0, TIPS['/runs/$id'].length))).toEqual(new Set(TIPS['/runs/$id']))
            expect(new Set(tips.slice(TIPS['/runs/$id'].length))).toEqual(new Set(ANYWHERE))
        }
    })

    it('never opens two views on the same tip, a list and one of its items included', () => {
        const views = [...(Object.keys(TIPS) as View[]), undefined]
        for (let day = 0; day < 12; day += 1) {
            const first = views.map((view) => tipFor(view, 0, day * DAY))
            expect(new Set(first).size).toBe(views.length)
        }
    })

    it('is the same for the same view, count, and day, and moves on with either', () => {
        expect(tipFor('/runs/', 1, 5 * DAY)).toBe(tipFor('/runs/', 1, 5 * DAY + 1000))
        expect(tipFor('/runs/', 1, 5 * DAY)).not.toBe(tipFor('/runs/', 2, 5 * DAY))
        expect(tipFor('/runs/', 0, 5 * DAY)).not.toBe(tipFor('/runs/', 0, 6 * DAY))
    })
})

describe('useBuddy', () => {
    beforeEach(() => localStorage.clear())

    it('turns Sprig on and off, and keeps the setting', async () => {
        const buddy = await load()
        const { result } = renderHook(() => buddy.useBuddy())
        expect(result.current).toBe('off')

        act(() => buddy.setBuddy('on'))
        expect(result.current).toBe('on')
        expect(localStorage.getItem(buddy.STORAGE_KEY)).toBe('on')
    })

    it("follows another tab's setting, one made before it was read, and storage cleared", async () => {
        const buddy = await load()
        localStorage.setItem(buddy.STORAGE_KEY, 'on')
        const { result } = renderHook(() => buddy.useBuddy())
        expect(result.current).toBe('on')

        act(() => otherTab(buddy.STORAGE_KEY, 'off'))
        expect(result.current).toBe('off')
        act(() => otherTab(buddy.STORAGE_KEY, 'on'))
        act(() => otherTab('canopy-theme', 'dark'))
        expect(result.current).toBe('on')
        act(() => otherTabClears())
        expect(result.current).toBe('off')
    })

    it('is off where storage is unavailable, and still turns on for this page', async () => {
        breakStorage()
        const buddy = await load()
        const { result } = renderHook(() => buddy.useBuddy())
        expect(result.current).toBe('off')

        act(() => buddy.setBuddy('on'))
        expect(result.current).toBe('on')
    })
})
