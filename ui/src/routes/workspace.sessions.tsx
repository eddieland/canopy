import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { sessionsQuery } from '@/api/queries'
import type { SessionList, SessionsWhose } from '@/api/types'
import { Code } from '@/components/code'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading } from '@/components/panel'
import { RowList } from '@/components/rows'
import { SessionRows, SessionsProgressLine } from '@/components/session-rows'
import { SESSIONS_LISTED, SESSIONS_MAX, SESSIONS_WHOSE, sessionsShown, WHOSE_CHIP, WHOSE_LABEL } from '@/lib/sessions'
import { cn } from '@/lib/utils'

interface SessionsSearch {
    canopy?: boolean | undefined
    archived?: boolean | undefined
    all?: boolean | undefined
}

/**
 * Every session the agent runtime keeps (DESIGN §13), newest first, as `canopy sessions` lists them: the ones outside
 * canopy, the operator's own, which no other page lists, or with `?canopy=true` canopy's runs', each opening the page
 * of the run that made it. A subagent's is under the session it ran for; an archived one only with `?archived=true`;
 * `?all=true` lists up to the server's most. Nothing at all while `sessions.search` is `off`. One of Workspace's pages,
 * beside the runs and the ticks.
 */
export const Route = createFileRoute('/workspace/sessions')({
    // Typed search params: each a flag, true or left out; anything else is dropped. Return every key (runs.index.tsx).
    validateSearch: (search: Record<string, unknown>): SessionsSearch => ({
        canopy: flag(search['canopy']),
        archived: flag(search['archived']),
        all: flag(search['all']),
    }),
    component: SessionsPage,
})

function flag(raw: unknown): true | undefined {
    return raw === true || raw === 'true' ? true : undefined
}

function SessionsPage() {
    const { canopy, archived, all } = Route.useSearch()
    const whose: SessionsWhose = canopy === true ? 'canopy' : 'outside'
    const query = useQuery(
        sessionsQuery({ whose, archived: archived === true, limit: all === true ? SESSIONS_MAX : SESSIONS_LISTED }),
    )
    const { data, isPlaceholderData } = query
    return (
        <>
            <PageHeader title="Sessions">
                Sessions the agent runtime keeps, newest first. Yours come with the command that reopens them;
                canopy&apos;s open the run that made them. Search finds them by title.
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
                                    search={{ canopy: w === 'canopy' ? true : undefined, archived, all }}
                                    selected={w === whose}
                                >
                                    {WHOSE_CHIP[w]}
                                </FilterLink>
                            ))}
                        </nav>
                        {/* A toggle, not a third choice of whose: set apart by a rule, and pressed or not. */}
                        <span className="flex items-center border-l pl-3">
                            <ArchivedToggle search={{ canopy, archived, all }} />
                        </span>
                        {data !== undefined && data.search !== 'off' && (
                            <span
                                className="border-l pl-3 readout text-xs text-muted-foreground"
                                data-testid="sessions-count"
                            >
                                {data.more ? `newest ${sessionsShown(data.sessions)}` : sessionsShown(data.sessions)}
                            </span>
                        )}
                    </span>
                </PanelHeader>
                {data === undefined ? (
                    <PanelLoading query={query} className="min-h-72" />
                ) : (
                    <Listed list={data} archived={archived === true} all={all === true} />
                )}
            </Panel>
        </>
    )
}

/** The list, or why it is empty, then how far the read has come and whether more sessions match. */
function Listed({ list, archived, all }: { list: SessionList; archived: boolean; all: boolean }) {
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
                <Empty size="panel">{emptyWords(list.whose, list.progress.read_at, archived)}</Empty>
            ) : (
                <RowList kind="session" className="divide-y" data-testid="sessions">
                    <SessionRows sessions={list.sessions} />
                </RowList>
            )}
            <p className="border-t px-3 py-2 text-xs text-muted-foreground" data-testid="sessions-progress">
                <SessionsProgressLine progress={list.progress} />
                {/* The way to the longest list, and back from it, one link in the same place, so its focus stays. */}
                {(list.more || all) && (
                    <>
                        {' '}
                        {all ? null : 'More match than these: '}
                        <Link
                            to="/workspace/sessions"
                            search={(prev) => ({ ...prev, all: all ? undefined : true })}
                            className="text-accent underline-offset-4 hover:underline"
                        >
                            {all ? `list the newest ${SESSIONS_LISTED}` : `list up to ${SESSIONS_MAX}`}
                        </Link>
                        .
                    </>
                )}
            </p>
        </>
    )
}

// What an empty list says: that the loop has read nothing yet, or that the runtime keeps no such session, or none it
// has not archived.
function emptyWords(whose: SessionsWhose, readAt: string | null, archived: boolean): string {
    if (readAt === null) {
        return "no sessions yet: canopy loop reads the runtime's sessions while it waits between ticks"
    }
    const noun = whose === 'canopy' ? "no session of canopy's" : 'no session outside canopy'
    return archived ? `${noun} yet` : `${noun} the runtime has not archived`
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
