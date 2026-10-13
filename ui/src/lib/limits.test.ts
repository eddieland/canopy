import { describe, expect, it } from 'vitest'

import type { Limit } from '@/api/types'

import { limitCount, limitLabel, stuck } from './limits'

const unit: Limit = { kind: 'fix-ci', repo: 'web', pr_url: null, runs: 1, granted: 0, limit: 1 }
const review: Limit = {
    kind: 'review',
    repo: 'web',
    pr_url: 'https://github.com/acme/web/pull/88',
    runs: 2,
    granted: 1,
    limit: 3,
}

describe('stuck', () => {
    it('keeps the limits whose runs have reached them, a grant counted', () => {
        const under = { ...unit, kind: 'implement' as const, runs: 1, limit: 2 }
        expect(stuck([unit, under, review])).toEqual([unit])
        expect(stuck([{ ...review, runs: 3 }])).toEqual([{ ...review, runs: 3 }])
    })
})

describe('limitLabel', () => {
    it("names a unit's kind and repository, and a PR's reviews by its repository and number", () => {
        expect(limitLabel(unit)).toBe('fix-ci in web')
        expect(limitLabel(review)).toBe('reviews of web#88')
        expect(limitLabel({ ...review, repo: null })).toBe('reviews of #88')
        expect(limitLabel({ ...review, pr_url: 'https://example.test/x' })).toBe('reviews')
    })
})

describe('limitCount', () => {
    it('says the runs against the limit, and the runs granted when there are any', () => {
        expect(limitCount(unit)).toBe('1 of 1 runs')
        expect(limitCount(review)).toBe('2 of 3 runs, 1 granted')
    })
})
