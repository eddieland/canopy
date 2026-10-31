import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setSeasons } from '@/lib/seasons'

import { SeasonSlot } from './season-slot'

beforeEach(() => {
    localStorage.clear()
    vi.useFakeTimers({ toFake: ['Date'], now: new Date(2026, 9, 30, 12) })
})

afterEach(() => {
    cleanup()
    act(() => setSeasons('on'))
    vi.useRealTimers()
    localStorage.clear()
})

describe('SeasonSlot', () => {
    it('stands the season at the foot of the rail with Sprig off', () => {
        render(<SeasonSlot />)
        expect(screen.getByTestId('buddy-season').dataset['season']).toBe('halloween')
    })

    it('leaves the rail bare out of season', () => {
        vi.setSystemTime(new Date(2026, 9, 8, 12))
        render(<SeasonSlot />)
        expect(screen.queryByTestId('rail-season')).toBeNull()
    })

    it('puts the season away when Settings turns the seasons off', () => {
        render(<SeasonSlot />)
        act(() => setSeasons('off'))
        expect(screen.queryByTestId('rail-season')).toBeNull()
    })
})
