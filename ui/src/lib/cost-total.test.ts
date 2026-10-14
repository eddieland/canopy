import { describe, expect, it } from 'vitest'

import { countedText } from './cost-total'

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
