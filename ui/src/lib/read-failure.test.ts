import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api/client'

import { readFailure, whyReadFailed } from './read-failure'

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

describe('whyReadFailed', () => {
    it("says what the server answered, or that canopy did not, without a write's doubt about what was done", () => {
        expect(whyReadFailed(new ApiError(500, undefined))).toBe('the server answered 500')
        expect(whyReadFailed(new ApiError(503, 'the runtime is starting'))).toBe(
            'the server answered 503: the runtime is starting',
        )
        expect(whyReadFailed(new TypeError('Failed to fetch'))).toBe(
            'canopy did not answer. `canopy loop` serves this page; is it running?',
        )
    })
})
