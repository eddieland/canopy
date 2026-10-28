import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { breakStorage, otherTab, otherTabClears } from '@/test-utils'

import { buy, EMPTY, parseVault, SHELLS, shellsCents } from './shells'

// The vault is read when the module loads, so each test loads a fresh copy.
function load() {
    vi.resetModules()
    return import('./shells')
}

describe('SHELLS', () => {
    it('is cheapest first, each shell once, the free one first', () => {
        const prices = SHELLS.map((s) => s.price)
        expect(prices).toEqual(prices.toSorted((a, b) => a - b))
        expect(new Set(SHELLS.map((s) => s.id)).size).toBe(SHELLS.length)
        expect(SHELLS[0]).toMatchObject({ id: 'generalist', price: 0 })
    })

    it('sells a Sprig Shell', () => {
        expect(SHELLS.find((s) => s.id === 'sprig')?.price).toBeGreaterThan(0)
    })
})

describe('parseVault', () => {
    it('is the free shell alone for anything it cannot read', () => {
        expect(parseVault(null)).toEqual(EMPTY)
        expect(parseVault('not json')).toEqual(EMPTY)
        expect(parseVault('3')).toEqual(EMPTY)
    })

    it('keeps the known shells, once each, in shop order, with the free one, and the worn one only if owned', () => {
        const raw = JSON.stringify({ owned: ['vex', 'exotic', 'sprig', 'sprig'], worn: 'vex' })
        expect(parseVault(raw)).toEqual({ owned: ['generalist', 'sprig', 'vex'], worn: 'vex' })
        expect(parseVault(JSON.stringify({ owned: ['sprig'], worn: 'gilded' }))).toEqual({
            owned: ['generalist', 'sprig'],
            worn: 'generalist',
        })
        expect(parseVault(JSON.stringify({ worn: null }))).toEqual(EMPTY)
    })
})

describe('shellsCents', () => {
    it('is what every shell bought cost, in cents, the free one nothing', () => {
        expect(shellsCents(['generalist'])).toBe(0)
        expect(shellsCents(['generalist', 'sprig', 'pumpkin'])).toBe(40_000)
    })
})

describe('buy', () => {
    it('adds the shell in shop order and puts it on', () => {
        const first = buy(EMPTY, 'pumpkin', 40_000)
        expect(first).toEqual({ owned: ['generalist', 'pumpkin'], worn: 'pumpkin' })
        expect(first && buy(first, 'sprig', 10_000)).toEqual({
            owned: ['generalist', 'sprig', 'pumpkin'],
            worn: 'sprig',
        })
    })

    it('refuses a shell the wallet cannot pay for, or one already owned', () => {
        expect(buy(EMPTY, 'gilded', 40_000)).toBeUndefined()
        expect(buy(EMPTY, 'sprig', 9999)).toBeUndefined()
        expect(buy(EMPTY, 'generalist', 1_000_000)).toBeUndefined()
    })
})

describe('useVault', () => {
    beforeEach(() => localStorage.clear())

    it('wears what is bought, and keeps it', async () => {
        const shells = await load()
        const { result } = renderHook(() => shells.useVault())
        expect(result.current).toEqual(EMPTY)

        const bought = shells.buy(result.current, 'sprig', 12_000)
        if (!bought) {
            throw new Error('the Sprig Shell is $100')
        }
        act(() => shells.setVault(bought))
        expect(result.current).toEqual({ owned: ['generalist', 'sprig'], worn: 'sprig' })
        expect(shells.parseVault(localStorage.getItem(shells.STORAGE_KEY))).toEqual(result.current)
    })

    it("follows another tab's vault, and storage cleared", async () => {
        const shells = await load()
        const { result } = renderHook(() => shells.useVault())

        act(() => otherTab(shells.STORAGE_KEY, JSON.stringify({ owned: ['sprig'], worn: 'sprig' })))
        expect(result.current).toEqual({ owned: ['generalist', 'sprig'], worn: 'sprig' })
        act(() => otherTabClears())
        expect(result.current).toEqual(EMPTY)
    })

    it('is the free shell where storage is unavailable, and still wears a shell for this page', async () => {
        breakStorage()
        const shells = await load()
        const { result } = renderHook(() => shells.useVault())
        expect(result.current).toEqual(EMPTY)

        act(() => shells.setVault({ owned: ['generalist', 'sprig'], worn: 'sprig' }))
        expect(result.current.worn).toBe('sprig')
    })
})
