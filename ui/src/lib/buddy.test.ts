import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { breakStorage, otherTab, otherTabClears } from '@/test-utils'

import { ANYWHERE, DEFAULT, nextTip, parseBuddy, RAVE, TIPS, tipsFor, typeBurst } from './buddy'
import type { View } from './buddy'

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
        const all = [...Object.values(TIPS).flat(), ...ANYWHERE, ...RAVE]
        expect(new Set(all).size).toBe(all.length)
    })

    it('never follows a voice with itself in a list, the last round to the first', () => {
        for (const tips of [...Object.values(TIPS), ANYWHERE, RAVE]) {
            const voices = tips.map((tip) => tip.split(' ').slice(0, 2).join(' '))
            for (const [n, voice] of voices.entries()) {
                expect(voice).not.toBe(voices[(n + 1) % voices.length])
            }
        }
    })

    it('keeps every tip short enough for the bubble', () => {
        // A longer tip makes the bubble taller, which the rail's slot must hold whole (src/components/shell/buddy.tsx).
        for (const tip of [...Object.values(TIPS).flat(), ...ANYWHERE, ...RAVE]) {
            expect(tip.length).toBeLessThanOrEqual(100)
        }
    })

    it('never opens a line with "Tip:", which is for the ticker\'s real tips', () => {
        for (const tip of [...Object.values(TIPS).flat(), ...ANYWHERE, ...RAVE]) {
            expect(tip).not.toMatch(/^Tip:/u)
        }
    })
})

// Draws `count` tips for a view, each with an even share of the range a random number falls in.
function drawAll(view: View | undefined, count: number, rave = false): Set<string> {
    return new Set(Array.from({ length: count }, (_, n) => nextTip(tipsFor(view, rave), '', () => n / count)))
}

describe('nextTip', () => {
    it("draws from the view's tips and the ones for anywhere, and nothing else", () => {
        const length = TIPS['/chores/$name'].length + ANYWHERE.length
        expect(drawAll('/chores/$name', length)).toEqual(new Set([...TIPS['/chores/$name'], ...ANYWHERE]))
    })

    it('draws only from the ones for anywhere off every view', () => {
        expect(drawAll(undefined, ANYWHERE.length)).toEqual(new Set(ANYWHERE))
    })

    it("draws only from the rave's while the lights rave, on any view", () => {
        expect(drawAll('/chores/$name', RAVE.length, true)).toEqual(new Set(RAVE))
        expect(drawAll(undefined, RAVE.length, true)).toEqual(new Set(RAVE))
    })

    it('never offers the tip just offered, on its view or another', () => {
        const views = [...(Object.keys(TIPS) as View[]), undefined]
        for (const view of views) {
            for (const last of tipsFor(view, false)) {
                for (const random of [0, 0.5, 0.999]) {
                    expect(nextTip(tipsFor(view, false), last, () => random)).not.toBe(last)
                }
            }
        }
    })
})

describe('typeBurst', () => {
    const keys = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i']

    it('types three to six keys, none twice, then the space bar', () => {
        for (const random of [0, 0.3, 0.6, 0.99]) {
            const burst = typeBurst(keys, ' ', () => random)
            expect(burst.length).toBeGreaterThanOrEqual(4)
            expect(burst.length).toBeLessThanOrEqual(7)
            expect(burst.at(-1)).toBe(' ')
            expect(new Set(burst).size).toBe(burst.length)
            expect(burst.slice(0, -1).every((key) => keys.includes(key))).toBe(true)
        }
    })

    it('picks its keys at random', () => {
        expect(typeBurst(keys, ' ', () => 0)).toEqual(['a', 'b', 'c', ' '])
        expect(typeBurst(keys, ' ', () => 0.99)).toEqual(['i', 'h', 'g', 'f', 'e', 'd', ' '])
    })

    it('types every key it has when it has fewer than a burst', () => {
        expect(typeBurst(['a', 'b'], ' ', () => 0.99)).toEqual(['b', 'a', ' '])
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
