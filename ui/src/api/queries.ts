import { keepPreviousData, queryOptions } from '@tanstack/react-query'

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
    run: (id: number) => ['run', id] as const,
    // A run's and a tick's transcripts: read again only when the stream says the run's status or the tick changed.
    runTranscript: (id: number) => ['transcript', 'run', id] as const,
    tickTranscript: (id: number) => ['transcript', 'tick', id] as const,
    tickets: ['tickets'] as const,
    ticket: (key: string) => ['ticket', key] as const,
    chores: ['chores'] as const,
    chore: (name: string) => ['chore', name] as const,
    // The ticks list and each tick's page share a prefix, so one invalidation marks both stale.
    ticks: ['ticks'] as const,
    tickDetail: (id: number) => ['ticks', id] as const,
    worktrees: ['worktrees'] as const,
    spend: ['spend'] as const,
    tick: ['tick'] as const,
    search: (q: string) => ['search', q] as const,
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

/** One run, as the runs list shows it. The stream writes a run it lists into this key when a page holds it. */
export function runQuery(id: number) {
    return queryOptions({
        queryKey: keys.run(id),
        queryFn: async ({ signal }) =>
            unwrap(await api.GET('/api/runs/{run_id}', { params: { path: { run_id: id } }, signal })),
        placeholderData: undefined,
    })
}

/**
 * A run's session, read back from its log by the server on every fetch (DESIGN §22). Its events reach the log when the
 * run ends, so it never goes stale on its own: the stream marks it stale when the run's status changes (live.ts).
 */
export function runTranscriptQuery(id: number) {
    return queryOptions({
        queryKey: keys.runTranscript(id),
        queryFn: async ({ signal }) =>
            unwrap(await api.GET('/api/runs/{run_id}/transcript', { params: { path: { run_id: id } }, signal })),
        placeholderData: undefined,
        staleTime: Number.POSITIVE_INFINITY,
    })
}

/** A tick's overseer session, read back from its output file. Marked stale when the stream says that tick changed. */
export function tickTranscriptQuery(id: number) {
    return queryOptions({
        queryKey: keys.tickTranscript(id),
        queryFn: async ({ signal }) =>
            unwrap(await api.GET('/api/ticks/{tick_id}/transcript', { params: { path: { tick_id: id } }, signal })),
        placeholderData: undefined,
        staleTime: Number.POSITIVE_INFINITY,
    })
}

/** What the last 24 hours and the last 30 days cost. The stream sends them again whenever a cost changes. */
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

/** The configured chores, as `canopy status` lists them. The stream sends the list again whenever it changes. */
export const choresQuery = queryOptions({
    queryKey: keys.chores,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/chores', { signal })),
})

/** One chore, as `canopy show chore:NAME` prints it. The stream marks it stale whenever the chores list changes. */
export function choreQuery(name: string) {
    return queryOptions({
        queryKey: keys.chore(name),
        queryFn: async ({ signal }) =>
            unwrap(await api.GET('/api/chores/{name}', { params: { path: { name } }, signal })),
        placeholderData: undefined,
    })
}

/** The latest ticks, newest first. Marked stale whenever the stream says the latest tick changed. */
export const ticksQuery = queryOptions({
    queryKey: keys.ticks,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/ticks', { signal })),
})

/** One tick and its decisions, as `canopy decisions ID` prints them. */
export function tickDetailQuery(id: number) {
    return queryOptions({
        queryKey: keys.tickDetail(id),
        queryFn: async ({ signal }) =>
            unwrap(await api.GET('/api/ticks/{tick_id}', { params: { path: { tick_id: id } }, signal })),
        placeholderData: undefined,
    })
}

/** How often the worktrees page reads the pools again while it is open in a visible tab. */
export const WORKTREES_REFRESH_MS = 10_000

/**
 * Each pool's worktrees, read from treehouse by the server on every fetch. Not on the event stream: the stream marks it
 * stale when a run starts or ends (live.ts), the page reads it again on demand, and every 10 seconds while a page shows
 * it and its tab is visible. That timer is the UI's one refetch on an interval: what runs in a slot,
 * whether it is dirty, and a slot sync adds never reach the journal.
 */
export const worktreesQuery = queryOptions({
    queryKey: keys.worktrees,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/worktrees', { signal })),
    refetchInterval: WORKTREES_REFRESH_MS,
    refetchIntervalInBackground: false,
})

/**
 * The journal's rows holding every word of `q` (DESIGN §22, Search). Not on the stream: read when the query changes.
 * The previous query's hits stay on screen while the next one's load, so typing never blanks the page.
 */
export function searchQuery(q: string) {
    return queryOptions({
        queryKey: keys.search(q),
        queryFn: async ({ signal }) => unwrap(await api.GET('/api/search', { params: { query: { q } }, signal })),
        placeholderData: keepPreviousData,
    })
}
