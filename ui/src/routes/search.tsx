import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'

import { searchQuery, sessionsQuery } from '@/api/queries'
import type { SearchHit, SearchSource, SessionsWhose } from '@/api/types'
import { Age } from '@/components/age'
import { ChoreLink, ChoreRunLink } from '@/components/chore-link'
import { MarkedText } from '@/components/marked-text'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading } from '@/components/panel'
import { ListRow, RowList } from '@/components/rows'
import { RunLink } from '@/components/run-link'
import { SessionRows, SessionsIndexLine } from '@/components/session-rows'
import { Chip, RunDot, Word } from '@/components/status'
import { TaskLink, TaskRunLink } from '@/components/task-link'
import { TickLink } from '@/components/tick-link'
import { TicketLink } from '@/components/ticket-link'
import { choreRunState } from '@/lib/chores'
import { RUN_TEXT } from '@/lib/run-state'
import { bySource, SEARCH_MIN, searchQueryOf, SOURCE_LABEL } from '@/lib/search'
import { indexBehind, SESSIONS_PER_SEARCH, SESSIONS_WHOSE, WHOSE_LABEL } from '@/lib/sessions'
import { cn } from '@/lib/utils'

interface SearchParams {
    q?: string | undefined
}

/** Search across the journal, with the query kept in `?q=`. */
export const Route = createFileRoute('/search')({
    // Typed search params: a query the server would refuse is dropped, so the page asks for one instead.
    validateSearch: (search: Record<string, unknown>): SearchParams => ({ q: searchQueryOf(search['q']) }),
    component: SearchPage,
})

function SearchPage() {
    const { q } = Route.useSearch()
    return (
        <>
            <PageHeader
                root="Search"
                title={q === undefined ? 'Search' : `“${q}”`}
                tab={q === undefined ? 'Search' : `Search “${q}”`}
            >
                Tickets by key, title, and branch, tasks by their text, every conversation, chore runs, decisions,
                ticks, and the agent runtime&apos;s sessions by their titles
                {q !== undefined && <SessionsByText q={q} />}, that hold every word, newest first. Not searched:
                transcripts, reviews, and task reports.
            </PageHeader>
            {q === undefined ? (
                <Panel>
                    <Empty size="panel">
                        no search yet: type at least {SEARCH_MIN} characters in the search box, or press /
                    </Empty>
                </Panel>
            ) : (
                <Results q={q} />
            )}
        </>
    )
}

/**
 * What the lede adds once the sessions are searched at `text`: that what they said is searched too. Nothing at
 * `titles` or `off`, or before the sessions are read. It reads by the first panel's key, so nothing is read twice.
 */
function SessionsByText({ q }: { q: string }) {
    const { data } = useQuery(sessionsQuery({ whose: 'outside', q, limit: SESSIONS_PER_SEARCH }))
    return data?.search === 'text' ? ' and what they said' : null
}

function Results({ q }: { q: string }) {
    const query = useQuery(searchQuery(q))
    const { data, isPlaceholderData } = query
    if (data === undefined) {
        return (
            <Panel>
                <PanelLoading query={query} className="min-h-72" />
            </Panel>
        )
    }
    const groups = bySource(data.hits)
    return (
        // The previous query's hits stay while the next one's load, dimmed so they do not read as its answer.
        <div
            className={cn('flex flex-col gap-6 transition-opacity', isPlaceholderData && 'opacity-60')}
            data-testid="search-results"
        >
            {groups.length === 0 && (
                <Panel>
                    <Empty size="panel">nothing in the journal holds every word</Empty>
                </Panel>
            )}
            {groups.map(([source, hits]) => (
                <Panel key={source} data-testid={`search-${source}`}>
                    <PanelHeader label={SOURCE_LABEL[source]}>
                        <span className="readout text-xs text-muted-foreground">
                            {data.more.includes(source) ? `newest ${hits.length}` : hits.length}
                        </span>
                    </PanelHeader>
                    <RowList kind="search-hit" className="divide-y">
                        {hits.map((hit) => (
                            <Row key={rowKey(hit)} hit={hit} words={data.words} />
                        ))}
                    </RowList>
                </Panel>
            ))}
            {SESSIONS_WHOSE.map((whose) => (
                <SessionsFound key={whose} q={q} whose={whose} />
            ))}
            <SessionsUnfound q={q} />
        </div>
    )
}

/**
 * One of the two panels of the runtime's sessions (DESIGN §13), after the journal's: those outside canopy, or
 * canopy's, the newest whose title holds every word, or at `text` the best matches of title and text, each with its
 * snippet, each opening its run's page or giving the command that reopens it. None while `sessions.search` is `off`,
 * or none matches, as a journal source with no hits has no panel. While the index may miss a session, still building
 * or failed, a line under the hits says how far it has come.
 */
function SessionsFound({ q, whose }: { q: string; whose: SessionsWhose }) {
    const { data } = useQuery(sessionsQuery({ whose, q, limit: SESSIONS_PER_SEARCH }))
    if (data === undefined || data.search === 'off' || data.sessions.length === 0) {
        return null
    }
    return (
        <Panel data-testid={`search-sessions-${whose}`}>
            <PanelHeader label={WHOSE_LABEL[whose]}>
                <span className="flex items-center gap-3">
                    {/* The same words on the Sessions page, where its filters and the longest list are. */}
                    <Link
                        to="/workspace/sessions"
                        search={{ q, canopy: whose === 'canopy' ? true : undefined }}
                        className="text-xs text-accent underline-offset-4 hover:underline"
                    >
                        find in Sessions
                    </Link>
                    <span className="readout text-xs text-muted-foreground">
                        {/* At text the hits are ranked, a title's word over a message's: the best, not the newest. */}
                        {data.more
                            ? `${data.search === 'text' ? 'best' : 'newest'} ${data.sessions.length}`
                            : data.sessions.length}
                    </span>
                </span>
            </PanelHeader>
            <RowList kind="session" className="divide-y">
                <SessionRows sessions={data.sessions} words={data.words} />
            </RowList>
            {indexBehind(data) && (
                <p className="border-t px-3 py-2 text-xs text-muted-foreground" data-testid="search-sessions-index">
                    <SessionsIndexLine list={data} />
                </p>
            )}
        </Panel>
    )
}

/**
 * A panel in place of the sessions' two when neither found one and the index of their text may have missed one: not
 * built, still building, failed, or built under another `sessions.exclude`. It says how far the index has come, so no
 * hit is not read as no such session. Nothing once the index is whole, as a source with no hits has no panel.
 */
function SessionsUnfound({ q }: { q: string }) {
    // The two panels' own reads, by the same keys, so nothing is read twice.
    const outside = useQuery(sessionsQuery({ whose: 'outside', q, limit: SESSIONS_PER_SEARCH })).data
    const canopy = useQuery(sessionsQuery({ whose: 'canopy', q, limit: SESSIONS_PER_SEARCH })).data
    if (outside === undefined || canopy === undefined) {
        return null
    }
    if (outside.sessions.length > 0 || canopy.sessions.length > 0 || !indexBehind(outside)) {
        return null
    }
    return (
        <Panel data-testid="search-sessions-unfound">
            <PanelHeader label="Sessions" />
            {/* An empty row and a foot, as a sessions panel with hits has rows and a foot: what was not found, then
                why that may not be the whole answer. */}
            <Empty>
                {outside.why_titles === null
                    ? 'no session found yet: the index of what sessions said does not hold every one'
                    : "no session's title holds every word"}
            </Empty>
            <p className="border-t px-3 py-2 text-xs text-muted-foreground" data-testid="search-sessions-index">
                <SessionsIndexLine list={outside} />
            </p>
        </Panel>
    )
}

function rowKey(hit: SearchHit) {
    return [hit.source, hit.ticket_key, hit.chore, hit.run_id, hit.tick_id, hit.at, hit.snippet].join('|')
}

function Row({ hit, words }: { hit: SearchHit; words: string[] }) {
    return (
        <ListRow kind="search-hit" className="items-baseline" data-testid="search-hit">
            <span className="flex min-w-0 flex-col gap-0.5">
                <Where hit={hit} />
            </span>
            <span className="flex min-w-0">
                <Label hit={hit} />
            </span>
            {/* Text, never markup; its URLs are not linked, since a snippet may cut one short. */}
            <p className="text-sm wrap-break-word">
                <MarkedText text={hit.snippet} words={words} />
            </p>
            <Age at={hit.at} variant="ago" className="text-right" />
        </ListRow>
    )
}

/**
 * A hit's fixed word: a chore run's status as a dot and its word in its state's color, as its chore's page lists it;
 * anything else's as a chip.
 */
function Label({ hit }: { hit: SearchHit }) {
    if (hit.label === null) {
        return null
    }
    if (hit.source === 'chore_run') {
        const state = choreRunState(hit.label)
        return (
            <span className={cn('flex min-w-0 items-center gap-1.5 font-mono text-xs', RUN_TEXT[state])}>
                <RunDot state={state} />
                <Word word={hit.label} className="truncate" />
            </span>
        )
    }
    return <Chip className="min-w-0 shrink" word={hit.label} />
}

const SUBJECT_FIRST: ReadonlySet<SearchSource> = new Set(['ticket', 'message', 'chore_run'])

/**
 * Where a hit opens: its ticket or chore, then the run that said it or the tick that decided it; or a task, or the
 * task's run that said it, over the task's first line.
 */
function Where({ hit }: { hit: SearchHit }) {
    if (hit.task_id !== null) {
        return (
            <TaskWhere task={hit.task_id} run={hit.source === 'message' ? hit.run_id : null} title={hit.task_title} />
        )
    }
    const subject =
        hit.ticket_key === null ? (
            hit.chore === null ? null : hit.source === 'chore_run' && hit.run_id !== null ? (
                <ChoreRunLink name={hit.chore} id={hit.run_id} />
            ) : (
                <ChoreLink name={hit.chore} />
            )
        ) : (
            <TicketLink ticketKey={hit.ticket_key} />
        )
    const tick = hit.tick_id === null ? null : <TickLink id={hit.tick_id} />
    // A chore run's own id names it (`chore:deps#2`) and opens its page; a message's is the run that reported it.
    const run = hit.run_id !== null && hit.source === 'message' ? <RunLink id={hit.run_id} /> : null
    if (SUBJECT_FIRST.has(hit.source)) {
        return (
            <>
                {subject}
                {run}
            </>
        )
    }
    return (
        <>
            {tick}
            {subject}
        </>
    )
}

/**
 * A task's hit: the task, or for a message one of its runs reported, that run (`task:4#5`, which names the task too),
 * over the task's first line, cut to the column with the whole line in its tip. The line is the operator's text.
 */
function TaskWhere({ task, run, title }: { task: number; run: number | null; title: string | null }) {
    return (
        <>
            {run === null ? <TaskLink id={task} /> : <TaskRunLink task={task} run={run} />}
            {title !== null && title !== '' && (
                <span className="truncate text-xs text-muted-foreground" title={title}>
                    {title}
                </span>
            )}
        </>
    )
}
