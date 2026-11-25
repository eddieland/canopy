import { describe, expect, it, vi } from 'vitest'

import { ApiError, TOKEN_HEADER, unwrap, withReadDeadline, writeToken } from './client'

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

// A server that takes the request and never answers: it settles only when the request is given up.
const silent: typeof fetch = (input) =>
    new Promise((_resolve, reject) => {
        const { signal } = input as Request
        signal.addEventListener('abort', () => {
            reject(signal.reason as Error)
        })
    })

describe('withReadDeadline', () => {
    it('fails a read the server never answers, once its deadline passes', async () => {
        vi.useFakeTimers()
        try {
            const read = withReadDeadline(silent, 1000)('http://127.0.0.1/api/x')
            const failure = read.then(
                () => null,
                (error: unknown) => error,
            )
            await vi.advanceTimersByTimeAsync(1000)
            expect(await failure).toMatchObject({ name: 'TimeoutError' })
        } finally {
            vi.useRealTimers()
        }
    })

    it('gives a write no deadline, since one cut short may have been done', async () => {
        vi.useFakeTimers()
        try {
            let settled = false
            const write = withReadDeadline(silent, 1000)('http://127.0.0.1/api/x', { method: 'POST' })
            void write.then(
                () => (settled = true),
                () => (settled = true),
            )
            await vi.advanceTimersByTimeAsync(60_000)
            expect(settled).toBe(false)
        } finally {
            vi.useRealTimers()
        }
    })

    it('still gives up a read when the page does, before the deadline', async () => {
        const page = new AbortController()
        const read = withReadDeadline(silent, 60_000)('http://127.0.0.1/api/x', { signal: page.signal })
        page.abort()
        await expect(read).rejects.toMatchObject({ name: 'AbortError' })
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

    it('throws an ApiError whose message is the words of any other failure, such as a busy journal', () => {
        const response = new Response(null, { status: 503 })
        const busy = { detail: 'the journal is busy: another writer held it for over 10s; try again' }
        let caught: unknown
        try {
            unwrap({ error: busy, response })
        } catch (error) {
            caught = error
        }
        expect(caught).toBeInstanceOf(ApiError)
        expect((caught as ApiError).guard).toBeNull()
        expect((caught as ApiError).message).toBe(busy.detail)
        expect((caught as ApiError).status).toBe(503)
    })
})
