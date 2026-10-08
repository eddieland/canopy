import { describe, expect, it } from 'vitest'

import { ApiError, TOKEN_HEADER, unwrap, writeToken } from './client'

function run(method: string, token: string | null): Request {
    const request = new Request('http://127.0.0.1/api/x', { method })
    const middleware = writeToken(() => token)
    const out = middleware.onRequest?.({ request } as Parameters<NonNullable<typeof middleware.onRequest>>[0])
    return out instanceof Request ? out : request
}

describe('writeToken', () => {
    it('adds the token to writes only', () => {
        expect(run('POST', 'tok').headers.get(TOKEN_HEADER)).toBe('tok')
        expect(run('DELETE', 'tok').headers.get(TOKEN_HEADER)).toBe('tok')
        expect(run('GET', 'tok').headers.get(TOKEN_HEADER)).toBeNull()
        expect(run('POST', null).headers.get(TOKEN_HEADER)).toBeNull()
    })
})

describe('unwrap', () => {
    it('returns data, or throws an ApiError carrying a refusal guard and reason', () => {
        const response = new Response(null, { status: 409 })
        expect(unwrap({ data: 1, response })).toBe(1)
        const refusal = { detail: { guard: 'not_started', reason: 'ABC-1 was not started in canopy' } }
        let caught: unknown
        try {
            unwrap({ error: refusal, response })
        } catch (error) {
            caught = error
        }
        expect(caught).toBeInstanceOf(ApiError)
        expect((caught as ApiError).guard).toBe('not_started')
        expect((caught as ApiError).message).toBe('ABC-1 was not started in canopy')
        expect((caught as ApiError).status).toBe(409)
    })
})
