import createClient from 'openapi-fetch'

import { basePath } from '@/lib/base'

import type { paths } from './schema.gen'

/** The typed API client. Paths and bodies are checked against canopy.serve's OpenAPI schema. */
export const api = createClient<paths>({ baseUrl: basePath })

/** Thrown for a non-2xx response, so TanStack Query sees a failure. */
export class ApiError extends Error {
    readonly status: number

    constructor(status: number, detail: unknown) {
        super(typeof detail === 'string' ? detail : `request failed with status ${status}`)
        this.name = 'ApiError'
        this.status = status
    }
}

/** Unwraps an openapi-fetch result: its data, or an ApiError. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
    if (result.data !== undefined) return result.data
    const detail = (result.error as { detail?: unknown } | undefined)?.detail
    throw new ApiError(result.response.status, detail)
}
