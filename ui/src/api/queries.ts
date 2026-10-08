import { queryOptions } from '@tanstack/react-query'

import { api, unwrap } from './client'

/**
 * Query keys and fetchers, one place for each. The SSE stream writes into these same keys (live.ts), so a key used
 * here and there must come from `keys`.
 */
export const keys = {
    meta: ['meta'] as const,
    sessions: ['sessions'] as const,
    leases: ['leases'] as const,
}

export const metaQuery = queryOptions({
    queryKey: keys.meta,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/meta', { signal })),
    staleTime: Number.POSITIVE_INFINITY,
})

export const sessionsQuery = queryOptions({
    queryKey: keys.sessions,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/sessions', { signal })),
})

export const leasesQuery = queryOptions({
    queryKey: keys.leases,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/leases', { signal })),
})
