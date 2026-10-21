import type { Capacity, ChoreRun, ChoreSummary, ReviewSummary, Run, RunState } from '@/api/types'

// Full class names, written out, so Tailwind finds them. One entry per state; the types make a missing one an error.

/** Each run state's dot: its status color as a fill. */
export const RUN_DOT: Record<RunState, string> = {
    running: 'bg-status-running',
    blocked: 'bg-status-blocked',
    stopped: 'bg-status-stopped',
    done: 'bg-status-done',
    failed: 'bg-status-failed',
}

/** Each run state's text color. */
export const RUN_TEXT: Record<RunState, string> = {
    running: 'text-status-running',
    blocked: 'text-status-blocked',
    stopped: 'text-status-stopped',
    done: 'text-status-done',
    failed: 'text-status-failed',
}

/**
 * Each run state in the operator's words, wherever the UI names a state rather than a run's own status: a filter's
 * chip, an empty filter's message. `blocked` asked a question, so it reads `waiting on you`, as the rail, the tickets
 * list, and the conversation say it. The URL and the journal keep `blocked`.
 */
export const RUN_WORD: Record<RunState, string> = {
    running: 'running',
    blocked: 'waiting on you',
    stopped: 'stopped',
    done: 'done',
    failed: 'failed',
}

/** One ticket's runs on the runs page: the latest, which says where the ticket stands, over the ones before it. */
export interface TicketRuns {
    /** The ticket's latest run: its running one, else the one that ended last. */
    latest: Run
    /** Its runs before that, the one that ended last first. */
    earlier: Run[]
}

/**
 * `runs`, in the order the server sends them, one entry per ticket, in the order of each ticket's latest run. A ticket
 * that asked a question, got its answer, and asked again is one entry, not two blocked ones.
 */
export function byTicket(runs: Run[]): TicketRuns[] {
    // The server sends the running runs first, then the rest by the one that ended last, and runs one worker per ticket
    // at a time: a ticket's first run in the list is its latest.
    const groups = new Map<string, TicketRuns>()
    for (const run of runs) {
        const group = groups.get(run.ticket_key)
        if (group === undefined) {
            groups.set(run.ticket_key, { latest: run, earlier: [] })
        } else {
            group.earlier.push(run)
        }
    }
    return [...groups.values()]
}

/** What a run on the runs page is a run of: a ticket's worker, a reviewer of a PR, or a chore. */
export type RunsOf = 'worker' | 'review' | 'chore'

/** Each kind of run, in the order the runs page's filter offers them. */
export const RUNS_OF: readonly RunsOf[] = ['worker', 'review', 'chore']

/** Each kind of run as the runs page's filter names it. */
export const RUNS_OF_WORD: Record<RunsOf, string> = {
    worker: 'workers',
    review: 'reviews',
    chore: 'chores',
}

/**
 * One subject's runs on the runs page, by its latest run: a ticket's worker runs, a PR's reviews, or a chore's runs. A
 * chore's earlier run is only its latest that ended, under one running now: the rest are on the chore's page.
 */
export type SubjectRuns =
    | ({ of: 'worker' } & TicketRuns)
    | { of: 'review'; latest: ReviewSummary; earlier: ReviewSummary[] }
    | { of: 'chore'; chore: string; title: string | null; latest: ChoreRun; earlier: ChoreRun[] }

/** Everything that runs an agent, as the runs page reads it: the worker runs, the review runs, and the chores. */
export interface EveryRun {
    /** The worker runs, as the server sends them: running first, then the ones that ended last. */
    runs: Run[]
    /** The review runs, newest first; undefined until they are read. */
    reviews?: ReviewSummary[] | undefined
    /** The chores, each with its running run and its latest that ended; undefined until they are read. */
    chores?: ChoreSummary[] | undefined
}

/**
 * One entry per subject: per ticket (`byTicket`), per PR reviewed, and per chore, each by its latest run. The ones
 * running come first, the one that started first leading, as the server sends a ticket's; then the rest, the one that
 * ended last first. Every run that holds a slot or spends tokens is on the page, whatever started it.
 */
export function subjectRuns({ runs, reviews = [], chores = [] }: EveryRun): SubjectRuns[] {
    const reviewed = new Map<string, { of: 'review'; latest: ReviewSummary; earlier: ReviewSummary[] }>()
    // Newest first, so a PR's first review in the list is its latest.
    for (const review of reviews) {
        const group = reviewed.get(review.pr_url)
        if (group === undefined) {
            reviewed.set(review.pr_url, { of: 'review', latest: review, earlier: [] })
        } else {
            group.earlier.push(review)
        }
    }
    const groups: SubjectRuns[] = [
        ...byTicket(runs).map(({ latest, earlier }) => ({ of: 'worker', latest, earlier }) as const),
        ...reviewed.values(),
        ...chores.flatMap((c) => {
            const latest = c.running ?? c.latest
            if (latest === null) {
                return []
            }
            const earlier = c.running !== null && c.latest !== null ? [c.latest] : []
            return [{ of: 'chore', chore: c.name, title: c.title, latest, earlier } as const]
        }),
    ]
    return groups.toSorted(byLatest)
}

/** How many runs `groups` list, each subject's earlier runs too. */
export function runsListed(groups: readonly SubjectRuns[]): number {
    return groups.reduce((sum, g) => sum + 1 + g.earlier.length, 0)
}

/**
 * What is running now against each limit of `[capacity]`, counted as the harness counts it when it refuses a start:
 * `workers` counts the worker runs and the review runs, as `max_workers` does, `reviews` the review runs alone, and
 * `chores` the chore runs, which `max_chores` counts apart.
 */
export function busy({ runs, reviews = [], chores = [] }: EveryRun): Capacity {
    const reviewing = reviews.filter((r) => r.state === 'running').length
    return {
        workers: runs.filter((r) => r.state === 'running').length + reviewing,
        reviews: reviewing,
        chores: chores.filter((c) => c.running !== null).length,
    }
}

// Running first, the one that started first leading; then the rest, the one that ended last first.
function byLatest(a: SubjectRuns, b: SubjectRuns): number {
    const [x, y] = [a.latest, b.latest]
    const running = Number(y.state === 'running') - Number(x.state === 'running')
    if (running !== 0) {
        return running
    }
    if (x.state === 'running') {
        return x.started_at.localeCompare(y.started_at)
    }
    return (y.ended_at ?? y.started_at).localeCompare(x.ended_at ?? x.started_at)
}

/** Each ticket's latest run, so a question a later run took up no longer counts as waiting. */
export function latestRuns(runs: Run[]): Run[] {
    return byTicket(runs).map((g) => g.latest)
}

/** A ticket's runs working now, oldest first. The harness runs one worker per ticket, so there is at most one. */
export function workingOn(runs: Run[], ticketKey: string): Run[] {
    return runs
        .filter((r) => r.state === 'running' && r.ticket_key === ticketKey)
        .toSorted((a, b) => a.started_at.localeCompare(b.started_at))
}

/** One thing the rail lists as working: a worker run, a review of a PR, or a chore's run. */
export type RailItem =
    | { kind: 'run'; run: Run }
    | { kind: 'review'; review: ReviewSummary }
    | { kind: 'chore'; chore: string; run: ChoreRun }

/** What the rail lists as working: the rows it shows, how many it leaves out, and the page that lists those. */
export interface RailWork {
    /** The rows shown, at most the limit. */
    shown: RailItem[]
    /** How many it leaves out. */
    more: number
    /** The page listing the ones left out: their kind's, or the runs page when they are of more than one kind. */
    moreAt: '/runs' | '/reviews' | '/chores'
}

/**
 * What the rail lists as working, at most `limit`: the worker runs, review runs, and chore runs running, then the
 * worker runs waiting on the operator's answer, each oldest first, so the work in progress leads and holds the slots.
 * Only each ticket's latest worker run counts: a blocked run a later one followed waits on nothing, and neither does
 * one whose ticket the operator stopped, as the attention list sets it aside.
 */
export function railWork(
    { runs, reviews = [], chores = [] }: { runs: Run[]; reviews?: ReviewSummary[]; chores?: ChoreSummary[] },
    limit: number,
): RailWork {
    const working: RailItem[] = [
        ...latestRuns(runs)
            .filter((r) => r.state === 'running' || (r.state === 'blocked' && !r.ticket_stopped))
            .map((run) => ({ kind: 'run', run }) as const),
        ...reviews.filter((r) => r.state === 'running').map((review) => ({ kind: 'review', review }) as const),
        ...chores.flatMap((c) => (c.running ? [{ kind: 'chore', chore: c.name, run: c.running } as const] : [])),
    ]
    const sorted = working.toSorted((a, b) => {
        const order = rank(a) - rank(b)
        return order === 0 ? startedAt(a).localeCompare(startedAt(b)) : order
    })
    const left = sorted.slice(limit)
    const kinds = new Set(left.map((item) => item.kind))
    const only = kinds.size === 1 ? [...kinds][0] : undefined
    return {
        shown: sorted.slice(0, limit),
        more: left.length,
        moreAt: only === 'review' ? '/reviews' : only === 'chore' ? '/chores' : '/runs',
    }
}

function rank(item: RailItem): number {
    return item.kind === 'run' && item.run.state === 'blocked' ? 1 : 0
}

function startedAt(item: RailItem): string {
    return item.kind === 'review' ? item.review.started_at : item.run.started_at
}
