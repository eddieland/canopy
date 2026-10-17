import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { HEADLINES } from '@/lib/headlines'
import { STORAGE_KEY } from '@/lib/ticker-settings'
import type { TickerSettings } from '@/lib/ticker-settings'
import { otherTab } from '@/test-utils'

import { Ticker } from './ticker'

// The tips alone, so the test knows which headline comes first and which next.
const TIPS_ONLY: Partial<TickerSettings> = { hidden: ['programming', 'vibes'] }
const [FIRST, SECOND] = HEADLINES.tips as [string, string]

// A ResizeObserver that measures once, as the browser does when it starts observing.
class MeasureOnce implements ResizeObserver {
    readonly #callback: ResizeObserverCallback

    constructor(callback: ResizeObserverCallback) {
        this.#callback = callback
    }

    observe(): void {
        this.#callback([], this)
    }

    disconnect(): void {}

    unobserve(): void {}
}

beforeEach(() => {
    localStorage.clear()
    vi.stubGlobal('ResizeObserver', MeasureOnce)
    // The first pick is the first headline, and each next one the one after it.
    vi.spyOn(Math, 'random').mockReturnValue(0)
})

afterEach(() => {
    cleanup()
    localStorage.clear()
})

// Renders the ticker in a window `rem` wide, with `settings` stored.
function renderTicker(settings: Partial<TickerSettings> = TIPS_ONLY, rem = 40) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(rem * 16)
    render(<Ticker />)
}

describe('Ticker', () => {
    it('crawls the first headline of the topics turned on', () => {
        renderTicker()
        expect(screen.getByRole('marquee', { name: 'Headlines' }).textContent).toBe(FIRST)
    })

    it('moves on to another headline when the crawl ends its pass, not when a letter of its flair does', () => {
        renderTicker()
        fireEvent.animationIteration(screen.getByText(FIRST))
        expect(screen.getByRole('marquee').textContent).toBe(FIRST)

        fireEvent.animationIteration(screen.getByTestId('ticker-headline'))
        expect(screen.getByRole('marquee').textContent).toBe(SECOND)
    })

    it.each<[string, Partial<TickerSettings>, number]>([
        ['turned off', { ...TIPS_ONLY, on: false }, 40],
        ['every topic is turned off', { hidden: ['programming', 'vibes', 'tips'] }, 40],
        ['the header leaves too little room to read in', TIPS_ONLY, 15],
    ])('shows no window when %s', (_, settings, rem) => {
        renderTicker(settings, rem)
        expect(screen.queryByRole('marquee')).toBeNull()
    })

    it('goes when another tab turns it off', () => {
        renderTicker()
        act(() => otherTab(STORAGE_KEY, JSON.stringify({ ...TIPS_ONLY, on: false })))
        expect(screen.queryByRole('marquee')).toBeNull()
    })
})
