import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { choresQuery, loopQuery, reviewsQuery, runsQuery, tasksQuery } from '@/api/queries'
import { RUN_STATES } from '@/api/types'
import type { Capacity, RunState } from '@/api/types'
import { ModelFilter } from '@/components/model-filter'
import { OrderToggle } from '@/components/order-toggle'
import { Empty, PageHeader, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { SubjectRunsTable } from '@/components/runs-table'
import { RunDot } from '@/components/status'
import { Tip } from '@/components/tip'
import { ordered, useListOrder } from '@/lib/list-order'
import { ranOn, runModelIds } from '@/lib/models'
import { busy, RUN_WORD, RUNS_OF, RUNS_OF_WORD, runningTasks, runsListed, subjectRuns } from '@/lib/run-state'
import type { EveryRun, RunsOf } from '@/lib/run-state'
import { cn } from '@/lib/utils'

interface RunsSearch {
    state?: RunState | undefined
    kind?: RunsOf | undefined
    model?: string | undefined
}

/**
 * Every run of an agent, a row per subject by its latest run: a ticket's worker runs, a PR's reviews, a chore's runs, a
 * task's newest run. Running ones first, then the ones that ended last. `?state=` keeps the subjects whose latest run
 * is in that state, and `?kind=` those of one kind. `?model=`, which the spend page's By model links to, keeps the
 * runs of every kind that model ran (`onModel`), each subject by its latest of them, its picker (`ModelFilter`)
 * offering each model the runs listed name. The overseer's ticks are under it, at `/runs/ticks`, and the worktree
 * pools, at `/runs/worktrees`.
 */
export const Route = createFileRoute('/runs/')({
    // Typed search params: `?state=blocked` filters; anything else is dropped, never trusted. Return every key, even
    // when undefined: the router merges this over the raw search, so an omitted key would keep the raw value.
    validateSearch: (search: Record<string, unknown>): RunsSearch => ({
        state: RUN_STATES.find((s) => s === search['state']),
        kind: RUNS_OF.find((k) => k === search['kind']),
        model: typeof search['model'] === 'string' && search['model'] !== '' ? search['model'] : undefined,
    }),
    component: RunsPage,
})

function RunsPage() {
    const { state, kind, model } = Route.useSearch()
    const runs = useQuery(runsQuery).data
    const reviews = useQuery(reviewsQuery).data
    const chores = useQuery(choresQuery).data
    const tasks = useQuery(tasksQuery).data
    const capacity = useQuery(loopQuery).data?.capacity
    // The worker runs lead the page: it waits on them, and lists the reviews, chores, and tasks as they arrive.
    const every = runs === undefined ? undefined : { runs, reviews, chores, tasks }
    const groups = every === undefined ? undefined : subjectRuns(onModel(every, model))
    // Every model the runs listed name, and the one chosen, which a run older than the list may be all that ran.
    const models = every === undefined ? [] : modelsOf(every, model)
    const navigate = Route.useNavigate()
    const shown = groups?.filter((g) => (state === undefined || g.latest.state === state) && (kind ?? g.of) === g.of)
    const order = useListOrder('runs')
    return (
        <>
            <PageHeader
                title="Runs"
                links={
                    runs !== undefined &&
                    capacity !== undefined && (
                        <CapacityLine
                            capacity={capacity}
                            busy={busy({ runs, reviews, chores, tasks })}
                            tasks={runningTasks(tasks ?? []).length}
                        />
                    )
                }
            >
                Every agent canopy runs: workers on tickets, reviews of PRs, chores, and tasks, each subject&apos;s
                latest run first, running ones on top, then the ones that ended last. A subject&apos;s earlier runs open
                under it. The overseer&apos;s ticks, and the worktree pools the runs work in, are under Runs too:{' '}
                <Link
                    to="/runs/ticks"
                    className="text-accent underline-offset-4 hover:underline"
                    data-testid="runs-ticks-link"
                >
                    Ticks
                </Link>{' '}
                and{' '}
                <Link
                    to="/runs/worktrees"
                    className="text-accent underline-offset-4 hover:underline"
                    data-testid="runs-worktrees-link"
                >
                    Worktrees
                </Link>
                .
            </PageHeader>
            <Panel>
                <PanelHeader label="Runs">
                    <span className="flex flex-wrap items-center gap-x-3">
                        <nav aria-label="Filter by kind" className="flex flex-wrap items-center gap-1">
                            <span className="mr-1 font-mono text-xs text-muted-foreground">kind</span>
                            <FilterLink search={{ state, kind: undefined, model }} selected={kind === undefined}>
                                all
                            </FilterLink>
                            {RUNS_OF.map((k) => (
                                <FilterLink key={k} search={{ state, kind: k, model }} selected={kind === k}>
                                    {RUNS_OF_WORD[k]}
                                </FilterLink>
                            ))}
                        </nav>
                        <nav aria-label="Filter by state" className="flex flex-wrap items-center gap-1">
                            <span className="mr-1 font-mono text-xs text-muted-foreground">state</span>
                            <FilterLink search={{ state: undefined, kind, model }} selected={state === undefined}>
                                all
                            </FilterLink>
                            {RUN_STATES.map((s) => (
                                <FilterLink key={s} search={{ state: s, kind, model }} selected={state === s}>
                                    <RunDot state={s} />
                                    {RUN_WORD[s]}
                                </FilterLink>
                            ))}
                        </nav>
                        {models.length > 0 && (
                            // A picker, as the repository's is, since a gateway or two can put dozens of models in
                            // the list; it replaces the history entry, as a filter field does.
                            <ModelFilter
                                models={models}
                                chosen={model}
                                onChoose={(m) => void navigate({ search: { state, kind, model: m }, replace: true })}
                            />
                        )}
                        {shown !== undefined && shown.length > 1 && <OrderToggle list="runs" />}
                        {shown !== undefined && (
                            // Every run listed, a subject's earlier ones too, as a ticket's Runs panel counts them.
                            <span className="readout text-xs text-muted-foreground" data-testid="runs-count">
                                {runsListed(shown)}
                            </span>
                        )}
                    </span>
                </PanelHeader>
                {shown === undefined ? (
                    <PanelSkeleton className="min-h-72" />
                ) : shown.length === 0 ? (
                    <Empty size="panel">
                        {state !== undefined || kind !== undefined || model !== undefined ? (
                            emptyWords(state, kind, model)
                        ) : (
                            <>
                                no runs yet: give a ticket your queue label, or start one privately on{' '}
                                <Link to="/tickets" className="text-accent underline-offset-4 hover:underline">
                                    Tickets
                                </Link>
                            </>
                        )}
                    </Empty>
                ) : (
                    <SubjectRunsTable groups={ordered('runs', order, shown)} />
                )}
            </Panel>
        </>
    )
}

// Every run the page lists, or under a model the runs it ran: a worker run by `ranOn`, so by the model canopy asked
// for until its session is read, a review by what its session named, a chore by its running or latest run's, and a
// task by its newest run's.
function onModel(every: EveryRun, model: string | undefined): EveryRun {
    if (model === undefined) {
        return every
    }
    return {
        runs: every.runs.filter((r) => ranOn(r, model)),
        reviews: every.reviews?.filter((r) => r.served.includes(model)),
        chores: every.chores?.filter((c) => [c.running, c.latest].some((r) => r?.served.includes(model) === true)),
        tasks: every.tasks?.filter((t) => t.latest?.served.includes(model) === true),
    }
}

// The models the model filter offers, sorted: every one the runs listed name, the one `chosen` among them.
function modelsOf(every: EveryRun, chosen: string | undefined): string[] {
    const ids = new Set(runModelIds(every.runs))
    for (const served of [
        ...(every.reviews ?? []).map((r) => r.served),
        ...(every.chores ?? []).flatMap((c) => [c.running?.served ?? [], c.latest?.served ?? []]),
        ...(every.tasks ?? []).map((t) => t.latest?.served ?? []),
    ]) {
        for (const id of served) {
            ids.add(id)
        }
    }
    if (chosen !== undefined) {
        ids.add(chosen)
    }
    return [...ids].toSorted()
}

// What a filter that keeps nothing says: `no reviews running now`, by each subject's latest run, or `no chores yet`.
// Under a model, the runs listed are the recent ones, so an older run on it may be out of the list.
function emptyWords(state: RunState | undefined, kind: RunsOf | undefined, model: string | undefined): string {
    const noun = kind === undefined ? 'runs' : RUNS_OF_WORD[kind]
    if (model !== undefined) {
        const on = `no recent ${noun} on ${model}`
        return state === undefined ? on : `${on} ${RUN_WORD[state]} now`
    }
    return state === undefined ? `no ${noun} yet` : `no ${noun} ${RUN_WORD[state]} now`
}

/**
 * What runs now against each limit of `[capacity]`, as the harness counts it when it refuses a start: the worker runs,
 * reviews, and task runs against `max_workers`, of which `tasks` are task runs, the reviews against `max_reviews`
 * within it, and the chores against `max_chores`. A limit that is full says so: the next dispatch of its kind waits
 * for a run to end.
 */
function CapacityLine({ capacity, busy: running, tasks }: { capacity: Capacity; busy: Capacity; tasks: number }) {
    return (
        <p className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs" data-testid="runs-capacity">
            <Limit
                name="workers"
                running={running.workers}
                limit={capacity.workers}
                fact={
                    `capacity.max_workers: worker runs, reviews, and task runs at once ` +
                    `(${running.reviews} running a review, ${tasks} a task)`
                }
            />
            <Limit
                name="reviews"
                running={running.reviews}
                limit={capacity.reviews}
                fact="capacity.max_reviews: reviews at once, within max_workers"
            />
            <Limit
                name="chores"
                running={running.chores}
                limit={capacity.chores}
                fact="capacity.max_chores: chore runs at once, apart from max_workers"
            />
        </p>
    )
}

function Limit({ name, running, limit, fact }: { name: string; running: number; limit: number; fact: string }) {
    // A limit of 0 turns its kind off: nothing waits on it, so it is not full.
    const full = limit > 0 && running >= limit
    return (
        <Tip fact={fact} mono>
            <span
                className={cn('readout', full ? 'text-status-blocked' : 'text-muted-foreground')}
                data-testid={`capacity-${name}`}
            >
                {name} {limit === 0 ? 'off' : `${running} of ${limit}`}
                {full && ' · full'}
            </span>
        </Tip>
    )
}

/** A filter chip, selected when it matches the validated search: an unknown value selects `all`. */
function FilterLink({
    search,
    selected,
    title,
    children,
}: {
    search: RunsSearch
    selected: boolean
    title?: string
    children: ReactNode
}) {
    return (
        <Link
            to="/runs"
            search={search}
            title={title}
            data-selected={selected}
            className={cn(
                'flex h-6 items-center gap-1.5 rounded-sm px-2 font-mono text-xs text-muted-foreground',
                'hover:bg-surface-raised hover:text-foreground',
                'data-[selected=true]:bg-accent/16 data-[selected=true]:text-foreground',
            )}
        >
            {children}
        </Link>
    )
}
