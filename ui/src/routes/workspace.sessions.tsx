import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { X } from 'lucide-react'
import type { ReactNode } from 'react'

import { sessionsQuery } from '@/api/queries'
import type { SessionList, SessionsWhose } from '@/api/types'
import { Code } from '@/components/code'
import { CostFilter } from '@/components/cost-filter'
import { FilterField } from '@/components/filter-field'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading } from '@/components/panel'
import { RowList } from '@/components/rows'
import { SessionRows, SessionsIndexLine, SessionsProgressLine } from '@/components/session-rows'
import { Tip } from '@/components/tip'
import { Button } from '@/components/ui/button'
import { SEARCH_MAX, searchQueryOf } from '@/lib/search'
import {
    costBoundOf,
    costBoundText,
    costBoundWords,
    directoryTail,
    indexBehind,
    SESSIONS_LISTED,
    SESSIONS_MAX,
    SESSIONS_WHOSE,
    sessionsShown,
    WHOSE_CHIP,
    WHOSE_LABEL,
} from '@/lib/sessions'
import type { CostBound } from '@/lib/sessions'
import { cn } from '@/lib/utils'

interface SessionsSearch {
    canopy?: boolean | undefined
    archived?: boolean | undefined
    all?: boolean | undefined
    directory?: string | undefined
    q?: string | undefined
    cost?: string | undefined
}

/**
 * Every session the agent runtime keeps (DESIGN §13), newest first, as `canopy sessions` lists them: the ones outside
 * canopy, the operator's own, which no other page lists, or with `?canopy=true` canopy's runs', each opening the page
 * of the run that made it. A subagent's is under the session it ran for; an archived one only with `?archived=true`;
 * `?all=true` lists up to the server's most. `?directory=`, which a row's directory links to, narrows the list to the
 * sessions that ran in that directory exactly, the server narrowing it, so the count and the longest list follow.
 * `?q=`, which the panel's field keeps, finds among them, with the other filters as they are, the sessions whose title
 * holds every word, or at `text` whose title and one message hold them between them, best match first, each with its
 * snippet, a subagent's in a row of its own. `?cost=`, a comparison and an amount in dollars as `gte:5`, which the
 * control beside the field keeps, narrows the list to the sessions whose own cost is within it, the server narrowing
 * it, a subagent's in a row of its own then too. Nothing at all while `sessions.search` is `off`. One of Workspace's
 * pages, beside the runs and the ticks.
 */
export const Route = createFileRoute('/workspace/sessions')({
    // Typed search params: each a flag, true or left out, and the directory a string or left out; anything else is
    // dropped. Return every key (runs.index.tsx).
    validateSearch: (search: Record<string, unknown>): SessionsSearch => ({
        canopy: flag(search['canopy']),
        archived: flag(search['archived']),
        all: flag(search['all']),
        directory:
            typeof search['directory'] === 'string' && search['directory'] !== '' ? search['directory'] : undefined,
        // A query the server would refuse is dropped, as the search page drops it: the list is then every session.
        q: searchQueryOf(search['q']),
        // A bound the page does not offer is dropped, and one it does is kept as the control writes it.
        cost: costOf(search['cost']),
    }),
    component: SessionsPage,
})

/** What the field finds a session by, at each setting that lists any: its placeholder and its name. */
const FOUND_BY = { titles: 'title', text: 'title or what was said' } as const

// Whether a list is in the order of how well each session matches, not of its age: one found by words at `text`.
function ranked(list: SessionList, q: string | undefined): boolean {
    return q !== undefined && list.search === 'text'
}

function costOf(raw: unknown): string | undefined {
    const bound = costBoundOf(raw)
    return bound === undefined ? undefined : costBoundText(bound)
}

function flag(raw: unknown): true | undefined {
    return raw === true || raw === 'true' ? true : undefined
}

function SessionsPage() {
    const { canopy, archived, all, directory, q, cost } = Route.useSearch()
    const bound = costBoundOf(cost)
    const navigate = useNavigate({ from: Route.fullPath })
    const whose: SessionsWhose = canopy === true ? 'canopy' : 'outside'
    const query = useQuery(
        sessionsQuery({
            whose,
            q,
            archived: archived === true,
            directory,
            ...(bound !== undefined && { [`cost_${bound.op}`]: bound.usd }),
            limit: all === true ? SESSIONS_MAX : SESSIONS_LISTED,
        }),
    )
    const { data, isPlaceholderData } = query
    return (
        <>
            <PageHeader title="Sessions">
                Sessions the agent runtime keeps, newest first. Yours come with the command that reopens them;
                canopy&apos;s open the run that made them. Find one by its title
                {data?.search === 'text' && ', by what it said,'} or by what it cost.
            </PageHeader>
            {/* The previous list stays while the next one loads, dimmed so it does not read as its answer. */}
            <Panel className={cn('transition-opacity', isPlaceholderData && 'opacity-60')}>
                <PanelHeader label={WHOSE_LABEL[whose]}>
                    <span className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1">
                        <nav aria-label="Whose sessions" className="flex items-center gap-1">
                            <span className="mr-1 font-mono text-xs text-muted-foreground">whose</span>
                            {SESSIONS_WHOSE.map((w) => (
                                <FilterLink
                                    key={w}
                                    search={{
                                        canopy: w === 'canopy' ? true : undefined,
                                        archived,
                                        all,
                                        directory,
                                        q,
                                        cost,
                                    }}
                                    selected={w === whose}
                                >
                                    {WHOSE_CHIP[w]}
                                </FilterLink>
                            ))}
                        </nav>
                        {/* A toggle, not a third choice of whose: set apart by a rule, and pressed or not. */}
                        <span className="flex items-center border-l pl-3">
                            <ArchivedToggle search={{ canopy, archived, all, directory, q, cost }} />
                        </span>
                        {directory !== undefined && (
                            <Narrowed directory={directory} search={{ canopy, archived, all, q, cost }} />
                        )}
                        {data !== undefined && data.search !== 'off' && (
                            <span
                                className="border-l pl-3 readout text-xs text-muted-foreground"
                                data-testid="sessions-count"
                            >
                                {data.more
                                    ? `${ranked(data, q) ? 'best' : 'newest'} ${sessionsShown(data.sessions)}`
                                    : sessionsShown(data.sessions)}
                            </span>
                        )}
                    </span>
                </PanelHeader>
                {/* The field stays while the next list loads, so typing never loses it; none at `off`. */}
                {data !== undefined && data.search !== 'off' && (
                    <search className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-3 py-2">
                        <FilterField
                            q={q}
                            queryOf={searchQueryOf}
                            onFilter={(words) =>
                                void navigate({ search: (prev) => ({ ...prev, q: words }), replace: true })
                            }
                            label={`Find sessions by ${FOUND_BY[data.search]}`}
                            placeholder={`Find by ${FOUND_BY[data.search]}`}
                            maxLength={SEARCH_MAX}
                            className="max-w-xl min-w-48 flex-1"
                        />
                        {/* At the row's end, over the costs it narrows. */}
                        <span className="ml-auto">
                            <CostFilter
                                bound={bound}
                                onFilter={(next) =>
                                    void navigate({
                                        search: (prev) => ({
                                            ...prev,
                                            cost: next === undefined ? undefined : costBoundText(next),
                                        }),
                                        replace: true,
                                    })
                                }
                            />
                        </span>
                    </search>
                )}
                {data === undefined ? (
                    <PanelLoading query={query} className="min-h-72" />
                ) : (
                    <Listed
                        list={data}
                        archived={archived === true}
                        all={all === true}
                        directory={directory}
                        q={q}
                        cost={bound}
                    />
                )}
            </Panel>
        </>
    )
}

/**
 * The list, or why it is empty, then how far the read has come and whether more sessions match, and at `text` how far
 * the index of what they said has.
 */
function Listed({
    list,
    archived,
    all,
    directory,
    q,
    cost,
}: {
    list: SessionList
    archived: boolean
    all: boolean
    directory: string | undefined
    q: string | undefined
    cost: CostBound | undefined
}) {
    if (list.search === 'off' || list.progress === null) {
        return (
            <Empty size="panel">
                no sessions listed: <Code>sessions.search</Code> is <Code>off</Code>. Set it to{' '}
                <Code>&quot;titles&quot;</Code> in your private config, and the loop&apos;s next wait reads every
                session&apos;s title
            </Empty>
        )
    }
    return (
        <>
            {list.sessions.length === 0 ? (
                <Empty size="panel">
                    {q === undefined
                        ? emptyWords(list.whose, list.progress.read_at, archived, directory, cost)
                        : unfoundWords(list, directory, cost)}
                </Empty>
            ) : (
                <RowList kind="session" className="divide-y" data-testid="sessions">
                    {/* Narrowed, every row's directory is the list's own: no link to the page it is on. */}
                    <SessionRows
                        sessions={list.sessions}
                        words={list.words}
                        narrow={directory === undefined}
                        costly={cost !== undefined}
                    />
                </RowList>
            )}
            {/* One foot, a line for each read: the titles', then the index's. */}
            <div className="flex flex-col gap-1 border-t px-3 py-2 text-xs text-muted-foreground">
                <p data-testid="sessions-progress">
                    <SessionsProgressLine progress={list.progress} />
                    {/* The way to the longest list and back, one link in the same place, so its focus stays. */}
                    {(list.more || all) && (
                        <>
                            {' '}
                            {all ? null : 'More match than these: '}
                            <Link
                                to="/workspace/sessions"
                                search={(prev) => ({ ...prev, all: all ? undefined : true })}
                                className="text-accent underline-offset-4 hover:underline"
                            >
                                {all
                                    ? `list the ${ranked(list, q) ? 'best' : 'newest'} ${SESSIONS_LISTED}`
                                    : `list up to ${SESSIONS_MAX}`}
                            </Link>
                            .
                        </>
                    )}
                </p>
                {(list.search === 'text' || list.why_titles !== null) && (
                    <p data-testid="sessions-index">
                        <SessionsIndexLine list={list} />
                    </p>
                )}
            </div>
        </>
    )
}

// What an empty list says: that the loop has read nothing yet, or that the runtime keeps no such session, in the
// directory the list is narrowed to, at the cost it is held to, or none it has not archived.
function emptyWords(
    whose: SessionsWhose,
    readAt: string | null,
    archived: boolean,
    directory: string | undefined,
    cost: CostBound | undefined,
): string {
    if (readAt === null) {
        return "no sessions yet: canopy loop reads the runtime's sessions while it waits between ticks"
    }
    const where = noSession(whose, directory)
    const left = archived ? '' : ', of those the runtime has not archived'
    if (cost !== undefined) {
        return `${where} ${costBoundWords(cost)}${left}`
    }
    return archived ? `${where} yet` : `${where} the runtime has not archived`
}

// What a list found by words says when it found none: what no session holds, where, and that the index may yet.
function unfoundWords(list: SessionList, directory: string | undefined, cost: CostBound | undefined): string {
    const noun = noSession(list.whose, directory)
    const where = cost === undefined ? noun : `${noun} that ${costBoundWords(cost)}`
    if (list.search !== 'text') {
        return `${where} has a title that holds every word`
    }
    return indexBehind(list)
        ? `${where} found yet: the index of what sessions said does not hold every one`
        : `${where} holds every word, in its title or in what it said`
}

// The sessions an empty list has none of: whose, and in which directory.
function noSession(whose: SessionsWhose, directory: string | undefined): string {
    const noun = whose === 'canopy' ? "no session of canopy's" : 'no session outside canopy'
    return directory === undefined ? noun : `${noun} in ${directory}`
}

// A filter chip's look, the runs page's: muted, and on the accent's tint while chosen.
const CHIP = [
    'flex h-6 items-center gap-1.5 rounded-sm px-2 font-mono text-xs text-muted-foreground',
    'hover:bg-surface-raised hover:text-foreground',
    'data-[selected=true]:bg-accent/16 data-[selected=true]:text-foreground',
]

/**
 * A filter chip: this page with `search`, marked when it is the one shown. The router marks it the current page only
 * when its search is the page's own, a key it leaves out included, so the default chip is not current under the other.
 */
function FilterLink({
    search,
    selected,
    children,
}: {
    search: SessionsSearch
    selected: boolean
    children: ReactNode
}) {
    return (
        <Link
            to="/workspace/sessions"
            search={search}
            activeOptions={{ explicitUndefined: true }}
            data-selected={selected}
            className={cn(CHIP)}
        >
            {children}
        </Link>
    )
}

/**
 * The directory the list is narrowed to, its end, the whole in its tip, after the group word `in`, and a button that
 * clears it, back to every directory's sessions with the page's other flags as they are (`search`).
 */
function Narrowed({ directory, search }: { directory: string; search: SessionsSearch }) {
    return (
        <span className="flex min-w-0 items-center gap-1 border-l pl-3" data-testid="sessions-directory">
            <span className="mr-1 font-mono text-xs text-muted-foreground">in</span>
            <Tip fact={directory} mono>
                <span className="truncate font-mono text-xs text-foreground">{directoryTail(directory)}</span>
            </Tip>
            <Button asChild variant="ghost" size="icon-xs" className="hover:bg-muted">
                <Link
                    to="/workspace/sessions"
                    search={{ ...search, directory: undefined }}
                    // Never the current page: the page's search holds the directory this one leaves out.
                    activeOptions={{ explicitUndefined: true }}
                    aria-label="Clear the directory"
                >
                    <X aria-hidden />
                </Link>
            </Button>
        </span>
    )
}

/**
 * The `archived` chip, a toggle kept in `?archived=true` as memory's history toggle is: pressed, the list holds the
 * sessions the runtime archived too.
 */
function ArchivedToggle({ search }: { search: SessionsSearch }) {
    const on = search.archived === true
    return (
        <Link
            to="/workspace/sessions"
            search={{ ...search, archived: on ? undefined : true }}
            // Never the current page: the toggle's search always differs from the page's in the key it flips.
            activeOptions={{ explicitUndefined: true }}
            aria-pressed={on}
            data-selected={on}
            className={cn(CHIP)}
        >
            archived
        </Link>
    )
}
