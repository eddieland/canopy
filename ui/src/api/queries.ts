import { queryOptions } from '@tanstack/react-query'

import { api, unwrap } from './client'

/**
 * Query keys and fetchers, one place for each. The SSE stream writes into these same keys (live.ts), so a key used
 * here and there must come from `keys`.
 */
export const keys = {
    session: ['session'] as const,
    meta: ['meta'] as const,
    attention: ['attention'] as const,
    runs: ['runs'] as const,
    tickets: ['tickets'] as const,
    ticket: (key: string) => ['ticket', key] as const,
    worktrees: ['worktrees'] as const,
    spend: ['spend'] as const,
    tick: ['tick'] as const,
}

/** Whether this browser is signed in. Never stale on its own: sign-in, sign-out, and a 401 set it. */
export const sessionQuery = queryOptions({
    queryKey: keys.session,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/session', { signal })),
    staleTime: Number.POSITIVE_INFINITY,
})

export const metaQuery = queryOptions({
    queryKey: keys.meta,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/meta', { signal })),
    staleTime: Number.POSITIVE_INFINITY,
})

export const attentionQuery = queryOptions({
    queryKey: keys.attention,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/attention', { signal })),
})

export const runsQuery = queryOptions({
    queryKey: keys.runs,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/runs', { signal })),
})

/** What the last 24 hours cost. The stream sends it again whenever the cost changes. */
export const spendQuery = queryOptions({
    queryKey: keys.spend,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/spend', { signal })),
})

/** The latest tick. The stream sends it again whenever a tick starts or ends. */
export const tickQuery = queryOptions({
    queryKey: keys.tick,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/tick', { signal })),
})

export const ticketsQuery = queryOptions({
    queryKey: keys.tickets,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/tickets', { signal })),
})

export function ticketQuery(key: string) {
    return queryOptions({
        queryKey: keys.ticket(key),
        queryFn: async ({ signal }) =>
            unwrap(await api.GET('/api/tickets/{key}', { params: { path: { key } }, signal })),
        // A ticket from another page's data is a different ticket: never show it while this one loads.
        placeholderData: undefined,
    })
}

/** How often the worktrees page reads the pools again while it is open in a visible tab. */
export const WORKTREES_REFRESH_MS = 30_000

/**
 * Each pool's worktrees, read from treehouse by the server on every fetch. Not on the event stream: the stream marks it
 * stale when a run starts or ends (live.ts), the page reads it again on demand, and every 30 seconds while a page shows
 * it and its tab is visible. That timer is the UI's one refetch on an interval (D090): what runs in a slot,
 * whether it is dirty, and a slot sync adds never reach the journal.
 */
export const worktreesQuery = queryOptions({
    queryKey: keys.worktrees,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/worktrees', { signal })),
    refetchInterval: WORKTREES_REFRESH_MS,
    refetchIntervalInBackground: false,
})
