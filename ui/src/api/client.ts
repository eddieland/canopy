import createClient from 'openapi-fetch'
import type { Middleware } from 'openapi-fetch'

import { basePath } from '@/lib/base'

import type { paths } from './schema.gen'

/** The typed API client. Paths and bodies are checked against canopy.serve's OpenAPI schema. */
export const api = createClient<paths>({ baseUrl: basePath })

/** The header a write carries its session's token in (canopy/serve/auth.py). */
export const TOKEN_HEADER = 'x-canopy-token'

const READS = new Set(['GET', 'HEAD'])

/**
 * Adds the session's token to every write. `token` reads it when the request is made, from the session query, so a
 * sign-in or sign-out needs no new client. The browser adds the same-origin Origin header itself.
 */
export function writeToken(token: () => string | null | undefined): Middleware {
    return {
        onRequest({ request }) {
            const value = token()
            if (!READS.has(request.method) && value) {
                request.headers.set(TOKEN_HEADER, value)
            }
            return request
        },
    }
}

/** Thrown for a non-2xx response, so TanStack Query sees a failure. A guard's refusal carries its guard's name. */
export class ApiError extends Error {
    /** The response's HTTP status. */
    readonly status: number
    /** The guard that refused the action, as the CLI names it, or null for any other failure. */
    readonly guard: string | null
    /** Whether the body said nothing of its own, so the message names only the status. */
    readonly bare: boolean

    /** An error for a response with `status` and its body's `detail`: a message, a refusal, or anything else. */
    constructor(status: number, detail: unknown) {
        super(message(status, detail))
        this.name = 'ApiError'
        this.status = status
        this.guard = refusalGuard(detail)
        this.bare = typeof detail !== 'string' && !isRefusal(detail)
    }
}

function message(status: number, detail: unknown): string {
    if (typeof detail === 'string') {
        return detail
    }
    if (isRefusal(detail)) {
        return detail.reason
    }
    return `request failed with status ${status}`
}

function isRefusal(detail: unknown): detail is { guard: string; reason: string } {
    return (
        typeof detail === 'object' &&
        detail !== null &&
        typeof (detail as { guard?: unknown }).guard === 'string' &&
        typeof (detail as { reason?: unknown }).reason === 'string'
    )
}

function refusalGuard(detail: unknown): string | null {
    return isRefusal(detail) ? detail.guard : null
}

/** Unwraps an openapi-fetch result: its data, or an ApiError. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
    if (result.data !== undefined) {
        return result.data
    }
    const detail = (result.error as { detail?: unknown } | undefined)?.detail
    throw new ApiError(result.response.status, detail)
}
