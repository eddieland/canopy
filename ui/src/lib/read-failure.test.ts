import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api/client'

import { readFailure } from './read-failure'

describe('readFailure', () => {
    it("says the server's status and its own words when it answered", () => {
        expect(readFailure(new ApiError(500, 'database is locked'))).toBe(
            'could not read it: the server answered 500: database is locked',
        )
    })

    it('says the status alone when the answer had no words of its own', () => {
        expect(readFailure(new ApiError(502, undefined))).toBe('could not read it: the server answered 502')
    })

    it('says canopy did not answer, and what serves the page, when no answer came', () => {
        expect(readFailure(new TypeError('Failed to fetch'))).toBe(
            'could not read it: canopy did not answer. `canopy loop` serves this page; is it running?',
        )
    })
})
