import { describe, expect, it } from 'vitest'

import { SECTIONS } from '@/lib/sections'

import { ANYWHERE, DEFAULT, pageOf, parseBuddy, TIPS, tipFor } from './buddy'

const DAY = 86_400_000

describe('parseBuddy', () => {
    it('is off unless turned on', () => {
        expect(DEFAULT).toBe('off')
        expect(parseBuddy(null)).toBe('off')
        expect(parseBuddy('on')).toBe('on')
        expect(parseBuddy('off')).toBe('off')
        expect(parseBuddy('maybe')).toBe('off')
    })
})

describe('pageOf', () => {
    it('names the page by the first part of its path it knows', () => {
        expect(pageOf('/attention')).toBe('/attention')
        expect(pageOf('/tickets/ABC-102')).toBe('/tickets')
        expect(pageOf('/canopy/ticks/2')).toBe('/ticks')
        expect(pageOf('/pull-requests/pr')).toBe('/pull-requests')
        expect(pageOf('/search')).toBe('/search')
        expect(pageOf('/')).toBeUndefined()
        expect(pageOf('/nowhere')).toBeUndefined()
    })
})

describe('TIPS', () => {
    it('has tips for every section of the nav', () => {
        for (const section of SECTIONS) {
            expect(TIPS[section].length).toBeGreaterThan(0)
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
    it("draws from the page's tips and the ones for anywhere", () => {
        const tips = new Set(Array.from({ length: 20 }, (_, n) => tipFor('/chores/deps', n, 0)))
        expect(tips).toEqual(new Set([...TIPS['/chores'], ...ANYWHERE]))
    })

    it('draws only from the ones for anywhere on a page it does not know', () => {
        expect(ANYWHERE).toContain(tipFor('/nowhere', 0, 0))
    })

    it("opens on the page's own tips, then the ones for anywhere", () => {
        for (let day = 0; day < 12; day += 1) {
            const tips = Array.from({ length: TIPS['/runs'].length + ANYWHERE.length }, (_, n) =>
                tipFor('/runs', n, day * DAY),
            )
            expect(new Set(tips.slice(0, TIPS['/runs'].length))).toEqual(new Set(TIPS['/runs']))
            expect(new Set(tips.slice(TIPS['/runs'].length))).toEqual(new Set(ANYWHERE))
        }
    })

    it('never opens two pages it knows on the same tip', () => {
        const pages = [...SECTIONS, '/search', '/nowhere']
        for (let day = 0; day < 12; day += 1) {
            const first = pages.map((page) => tipFor(page, 0, day * DAY))
            expect(new Set(first).size).toBe(pages.length)
        }
    })

    it('is the same for the same page, count, and day, and moves on with either', () => {
        expect(tipFor('/runs', 1, 5 * DAY)).toBe(tipFor('/runs', 1, 5 * DAY + 1000))
        expect(tipFor('/runs', 1, 5 * DAY)).not.toBe(tipFor('/runs', 2, 5 * DAY))
        expect(tipFor('/runs', 0, 5 * DAY)).not.toBe(tipFor('/runs', 0, 6 * DAY))
    })
})
