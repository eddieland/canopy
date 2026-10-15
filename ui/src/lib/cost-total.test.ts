import { describe, expect, it } from 'vitest'

import { costText, countedText } from './cost-total'

describe('costText', () => {
    it('shows dollars to the cent, or a dash when nothing reported a cost', () => {
        expect(costText(0.4)).toBe('$0.40')
        expect(costText(null)).toBe('–')
    })

    it('groups the dollars by thousands', () => {
        expect(costText(1234.5)).toBe('$1,234.50')
        expect(costText(25_000)).toBe('$25,000.00')
    })

    it('rounds to the cent as the CLI does', () => {
        expect(costText(0.47 / 2)).toBe('$0.23')
    })
})

describe('countedText', () => {
    it('names the runs and reviews a total counted', () => {
        expect(countedText({ runs: 3, reviews: 1, priced: 4, cost_usd: 2.5 })).toBe('over 3 runs and 1 review')
        expect(countedText({ runs: 1, reviews: 0, priced: 1, cost_usd: 0.4 })).toBe('over 1 run')
        expect(countedText({ runs: 0, reviews: 2, priced: 2, cost_usd: 0.4 })).toBe('over 2 reviews')
    })

    it('says how many reported no cost', () => {
        expect(countedText({ runs: 2, reviews: 1, priced: 1, cost_usd: 0.4 })).toBe(
            'over 2 runs and 1 review, 2 unpriced',
        )
        expect(countedText({ runs: 1, reviews: 0, priced: 0, cost_usd: null })).toBe('over 1 run, 1 unpriced')
    })

    it('says so when nothing has run', () => {
        expect(countedText({ runs: 0, reviews: 0, priced: 0, cost_usd: null })).toBe('nothing has run')
    })
})
