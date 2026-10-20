import { keepPreviousData, queryOptions } from '@tanstack/react-query'

import { api, unwrap } from './client'

/** The window a spend breakdown reads: local days, by the day, or clock hours, by the hour. */
export type SpendBreakdownRange = { days: number; hours?: undefined } | { hours: number; days?: undefined }

/**
 * Query keys and fetchers, one place for each. The SSE stream writes into these same keys (live.ts), so a key used
 * here and there must come from `keys`.
 */
export const keys = {
    session: ['session'] as const,
    // Under the session's key, so signing in, which reads every other query again, and signing out, which drops
    // them, leave it to the sign-in page.
    unsent: ['session', 'unsent'] as const,
    meta: ['meta'] as const,
    attention: ['attention'] as const,
    runs: ['runs'] as const,
    run: (id: number) => ['run', id] as const,
    runsSince: (since: string) => ['runs-since', since] as const,
    // A run's and a tick's transcripts: read again only when the stream says the run's status or the tick changed.
    runTranscript: (id: number) => ['transcript', 'run', id] as const,
    runOutput: (id: number) => ['transcript', 'run', id, 'output'] as const,
    tickTranscript: (id: number) => ['transcript', 'tick', id] as const,
    // Under its transcript's key, so the invalidation that marks the transcript stale marks the output too.
    tickOutput: (id: number) => ['transcript', 'tick', id, 'output'] as const,
    tickets: ['tickets'] as const,
    ticket: (key: string) => ['ticket', key] as const,
    // Under the ticket's key, so the stream's `ticket.changed` marks its plans stale too: a plan run's end changes
    // both.
    ticketPlans: (key: string) => ['ticket', key, 'plans'] as const,
    ticketPlan: (key: string, id: number) => ['ticket', key, 'plans', id] as const,
    chores: ['chores'] as const,
    chore: (name: string) => ['chore', name] as const,
    // A chore run, and its transcript: read again only when the stream says the run's status changed.
    choreRun: (name: string, id: number) => ['chore-run', name, id] as const,
    choreRunTranscript: (name: string, id: number) => ['transcript', 'chore-run', name, id] as const,
    // The ticks list and each tick's page share a prefix, so one invalidation marks both stale.
    ticks: ['ticks'] as const,
    tickDetail: (id: number) => ['ticks', id] as const,
    worktrees: ['worktrees'] as const,
    spend: ['spend'] as const,
    // Under the spend's key, so the stream's `spend.updated` marks every window's breakdown stale.
    spendBreakdown: (range: SpendBreakdownRange) =>
        ['spend', 'breakdown', range.hours === undefined ? `${range.days}d` : `${range.hours}h`] as const,
    tick: ['tick'] as const,
    search: (q: string) => ['search', q] as const,
    // The reviews list, the reviews waiting on a tick, and each review's page share a prefix, so one invalidation
    // marks them all stale.
    reviews: ['reviews'] as const,
    reviewRequests: ['reviews', 'requested'] as const,
    review: (id: number) => ['reviews', id] as const,
    // The PRs list and each PR's page share a prefix, so one invalidation marks both stale.
    pullRequests: ['pull-requests'] as const,
    pullRequest: (url: string) => ['pull-requests', url] as const,
    // Under the PR's key, so what marks its page stale marks its threads stale too.
    pullRequestThreads: (url: string) => ['pull-requests', url, 'threads'] as const,
    loop: ['loop'] as const,
    // Agent memory: every tier's, read again at each tick; a ticket's under its ticket's key, so the stream's
    // `ticket.changed` marks it stale with the ticket; a run's, read again when the run's status changes.
    memory: ['memory'] as const,
    ticketMemory: (key: string) => ['ticket', key, 'memory'] as const,
    runMemory: (id: number) => ['run-memory', id] as const,
}

/** Whether this browser is signed in. Never stale on its own: sign-in, sign-out, and a 401 set it. */
export const sessionQuery = queryOptions({
    queryKey: keys.session,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/session', { signal })),
    staleTime: Number.POSITIVE_INFINITY,
})

/**
 * Whether the page was signed out by a 401 to a write, so what the operator last did was not sent. Not read from the
 * server: the query client sets it on that 401 (`src/lib/query-client.ts`), and signing in clears it.
 */
export const unsentQuery = queryOptions({
    queryKey: keys.unsent,
    queryFn: () => false,
    staleTime: Number.POSITIVE_INFINITY,
})

/**
 * The server itself: its version and UI build, whether its data is mock, and its link templates. Never stale on its
 * own: the stream's reconnect marks it stale, since the server may have restarted on a newer version (useLiveUpdates).
 */
export const metaQuery = queryOptions({
    queryKey: keys.meta,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/meta', { signal })),
    staleTime: Number.POSITIVE_INFINITY,
})

/** The attention list. The stream sends it again whenever it changes. */
export const attentionQuery = queryOptions({
    queryKey: keys.attention,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/attention', { signal })),
})

/** Running runs, then the ones that ended most recently. The stream sends the list again whenever it changes. */
export const runsQuery = queryOptions({
    queryKey: keys.runs,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/runs', { signal })),
})

/**
 * What the runs did since `since`, counted over the whole journal rather than the runs list's recent few: the note
 * on coming back to a tab left hidden (`useAwayNote`). Not on the stream: read once, when the tab is shown again.
 */
export function runsSinceQuery(since: string) {
    return queryOptions({
        queryKey: keys.runsSince(since),
        queryFn: async ({ signal }) =>
            unwrap(await api.GET('/api/runs/since', { params: { query: { since } }, signal })),
    })
}

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

/** The end of a tick's output file as written, stderr included. Stale when its transcript is. */
export function tickOutputQuery(id: number) {
    return queryOptions({
        queryKey: keys.tickOutput(id),
        queryFn: async ({ signal }) =>
            unwrap(await api.GET('/api/ticks/{tick_id}/output', { params: { path: { tick_id: id } }, signal })),
        placeholderData: undefined,
        staleTime: Number.POSITIVE_INFINITY,
    })
}

/** The end of a run's log as written, its setup commands' output and stderr included. Stale when its transcript is. */
export function runOutputQuery(id: number) {
    return queryOptions({
        queryKey: keys.runOutput(id),
        queryFn: async ({ signal }) =>
            unwrap(await api.GET('/api/runs/{run_id}/output', { params: { path: { run_id: id } }, signal })),
        placeholderData: undefined,
        staleTime: Number.POSITIVE_INFINITY,
    })
}

/** What the last 24 hours and the last 30 days cost. The stream sends them again whenever a cost changes. */
export const spendQuery = queryOptions({
    queryKey: keys.spend,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/spend', { signal })),
})

/**
 * What the last `days` local days cost, by day and by what the ticks bought, as `canopy spend --days` prints it, or the
 * last `hours` clock hours, by the hour. The stream's `spend.updated` marks it stale.
 */
export function spendBreakdownQuery(range: SpendBreakdownRange) {
    return queryOptions({
        queryKey: keys.spendBreakdown(range),
        queryFn: async ({ signal }) =>
            unwrap(await api.GET('/api/spend/breakdown', { params: { query: range }, signal })),
    })
}

/** The latest tick. The stream sends it again whenever a tick starts or ends. */
export const tickQuery = queryOptions({
    queryKey: keys.tick,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/tick', { signal })),
})

/** Whether the operator paused the loop (docs/DESIGN.md §6). The stream sends it again whenever it changes. */
export const loopQuery = queryOptions({
    queryKey: keys.loop,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/loop', { signal })),
})

/** Every ticket canopy has worked or been asked to. The stream sends the list again whenever it changes. */
export const ticketsQuery = queryOptions({
    queryKey: keys.tickets,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/tickets', { signal })),
})

/** One ticket, as `canopy show` prints it. The stream marks it stale when it says that ticket changed. */
export function ticketQuery(key: string) {
    return queryOptions({
        queryKey: keys.ticket(key),
        queryFn: async ({ signal }) =>
            unwrap(await api.GET('/api/tickets/{key}', { params: { path: { key } }, signal })),
        // A ticket from another page's data is a different ticket: never show it while this one loads.
        placeholderData: undefined,
    })
}

/** A ticket's plans: whether it needs one, its newest as the file stands, every plan, and the comments (DESIGN §25). */
export function ticketPlansQuery(key: string) {
    return queryOptions({
        queryKey: keys.ticketPlans(key),
        queryFn: async ({ signal }) =>
            unwrap(await api.GET('/api/tickets/{key}/plans', { params: { path: { key } }, signal })),
        placeholderData: undefined,
    })
}

/** One of a ticket's plans, an earlier one too, as its file stands: what `canopy show --plans` prints. */
export function ticketPlanQuery(key: string, id: number) {
    return queryOptions({
        queryKey: keys.ticketPlan(key, id),
        queryFn: async ({ signal }) =>
            unwrap(
                await api.GET('/api/tickets/{key}/plans/{plan_id}', { params: { path: { key, plan_id: id } }, signal }),
            ),
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

/**
 * One run of a chore, with the whole of what it reported. It changes only as the run ends, so the stream marks it
 * stale when the run's status changes (live.ts), as it does the run's transcript.
 */
export function choreRunQuery(name: string, id: number) {
    return queryOptions({
        queryKey: keys.choreRun(name, id),
        queryFn: async ({ signal }) =>
            unwrap(
                await api.GET('/api/chores/{name}/runs/{run_id}', { params: { path: { name, run_id: id } }, signal }),
            ),
        placeholderData: undefined,
        staleTime: Number.POSITIVE_INFINITY,
    })
}

/** A chore run's session, read back from its log by the server on every fetch, as a run's is (DESIGN §22). */
export function choreRunTranscriptQuery(name: string, id: number) {
    return queryOptions({
        queryKey: keys.choreRunTranscript(name, id),
        queryFn: async ({ signal }) =>
            unwrap(
                await api.GET('/api/chores/{name}/runs/{run_id}/transcript', {
                    params: { path: { name, run_id: id } },
                    signal,
                }),
            ),
        placeholderData: undefined,
        staleTime: Number.POSITIVE_INFINITY,
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
 * Each pool's worktrees, read from the pool by the server on every fetch. Not on the event stream: the stream marks it
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

/**
 * canopy's latest review runs, newest first. The stream sends the list again whenever a review starts, ends, or its
 * cost moves; the ticks mark it and each review's page stale too, as a tick can make a review's PR the loop's own.
 */
export const reviewsQuery = queryOptions({
    queryKey: keys.reviews,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/reviews', { signal })),
})

/**
 * The PRs the operator asked canopy to review that no review of is running yet, newest first: each waits on a tick to
 * start one. The stream sends the list again whenever one is asked for, starts, or ends.
 */
export const reviewRequestsQuery = queryOptions({
    queryKey: keys.reviewRequests,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/review-requests', { signal })),
})

/** The PRs the journal knows, most recent activity first. Marked stale on every tick and every ticket change. */
export const pullRequestsQuery = queryOptions({
    queryKey: keys.pullRequests,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/pull-requests', { signal })),
})

/** One PR: the runs that pushed to it, its reviews, and the decisions naming it. Stale as the PRs list is. */
export function pullRequestQuery(url: string) {
    return queryOptions({
        queryKey: keys.pullRequest(url),
        queryFn: async ({ signal }) =>
            unwrap(await api.GET('/api/pull-request', { params: { query: { url } }, signal })),
        placeholderData: undefined,
    })
}

/**
 * A PR's review threads on the diff its latest run kept, with every draft for it (DESIGN §29): what canopy's reader
 * last read, never live from GitHub. A 404 is a PR canopy has read no threads of and holds no draft for.
 */
export function pullRequestThreadsQuery(url: string) {
    return queryOptions({
        queryKey: keys.pullRequestThreads(url),
        queryFn: async ({ signal }) =>
            unwrap(await api.GET('/api/pull-request/threads', { params: { query: { url } }, signal })),
        placeholderData: undefined,
    })
}

/** One review run in full: its findings, and the diff they sit on, read back from beside its log on every fetch. */
export function reviewQuery(id: number) {
    return queryOptions({
        queryKey: keys.review(id),
        queryFn: async ({ signal }) =>
            unwrap(await api.GET('/api/reviews/{run_id}', { params: { path: { run_id: id } }, signal })),
        placeholderData: undefined,
    })
}

/** Every tier of agent memory (DESIGN §28): the notes in force, the proposals waiting, the lessons. Reads only. */
export const memoryQuery = queryOptions({
    queryKey: keys.memory,
    queryFn: async ({ signal }) => unwrap(await api.GET('/api/memory', { signal })),
})

/**
 * Every tier of agent memory with its history: the latest proposals and lessons no longer pending or in force too.
 * Under the memory key, so what reads memory again reads this too.
 */
export const memoryHistoryQuery = queryOptions({
    queryKey: [...keys.memory, 'history'] as const,
    queryFn: async ({ signal }) =>
        unwrap(await api.GET('/api/memory', { params: { query: { history: true } }, signal })),
})

/**
 * What `canopy memory search` finds as the operator (DESIGN §28, Search) among the ticket notes in force, whose key or
 * text holds every one of `q`'s words, as the page's filter keeps its rows, best match first, at most
 * `MEMORY_FOUND_MAX`: the page lists only those, so its 50 are never spent on lessons.
 * Under the memory key, so what reads memory again reads this too; the last result stays while the next is read, so
 * the list does not blink as the operator types.
 */
export function memorySearchQuery(q: string) {
    return queryOptions({
        queryKey: [...keys.memory, 'search', q] as const,
        queryFn: async ({ signal }) =>
            unwrap(await api.GET('/api/memory/search', { params: { query: { q, notes: true, every: true } }, signal })),
        placeholderData: (previous) => previous,
    })
}

/** A ticket's notes, and what its next run would be served (DESIGN §28). */
export function ticketMemoryQuery(key: string) {
    return queryOptions({
        queryKey: keys.ticketMemory(key),
        queryFn: async ({ signal }) =>
            unwrap(await api.GET('/api/tickets/{key}/memory', { params: { path: { key } }, signal })),
        placeholderData: undefined,
    })
}

/**
 * Every version of a lesson or a note, newest first (DESIGN §28): each edit of a lesson, each note under its key. Under
 * the memory key, so what reads memory again reads this too.
 */
export function memoryVersionsQuery(id: number) {
    return queryOptions({
        queryKey: [...keys.memory, 'versions', id] as const,
        queryFn: async ({ signal }) =>
            unwrap(await api.GET('/api/memory/{memory_id}/history', { params: { path: { memory_id: id } }, signal })),
    })
}

/** What a run wrote and read of memory, and what it had refused (DESIGN §28). */
export function runMemoryQuery(id: number) {
    return queryOptions({
        queryKey: keys.runMemory(id),
        queryFn: async ({ signal }) =>
            unwrap(await api.GET('/api/runs/{run_id}/memory', { params: { path: { run_id: id } }, signal })),
        placeholderData: undefined,
    })
}
