import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { History, Pin } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'

import { memoryHistoryQuery, memoryQuery, memorySearchQuery, ticketMemoryQuery } from '@/api/queries'
import type {
    MemoryDigest,
    MemoryEntry,
    MemoryOverview,
    MemoryProposal,
    MemoryState,
    MemoryTier,
    TicketNotes,
} from '@/api/types'
import { Age } from '@/components/age'
import { Code } from '@/components/code'
import { Disclosure } from '@/components/disclosure'
import { SearchField } from '@/components/input'
import { MemoryBand, MemoryDigestFold, MemoryPurge, MemoryRows, ProposalFacts } from '@/components/memory'
import { LessonActions, MemorySaid, NoteActions, ProposalActions } from '@/components/memory-actions'
import { OrderToggle } from '@/components/order-toggle'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelScroll, PanelSkeleton } from '@/components/panel'
import { RepoFilter } from '@/components/repo-picker'
import { ListRow } from '@/components/rows'
import { RunDot } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { TicketTitle } from '@/components/ticket-title'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { ordered, useListOrder } from '@/lib/list-order'
import { lessonGroups, ticketNotesUsedText } from '@/lib/memory'
import type { TierModes } from '@/lib/memory'
import {
    foundCount,
    MEMORY_FOUND_MAX,
    MEMORY_QUERY_MAX,
    MEMORY_SHOWS,
    memoryQueryOf,
    memoryShowOf,
    memoryShown,
    shownCount,
    ticketNotesShown,
} from '@/lib/memory-filter'
import type { MemoryFilter, MemoryShow } from '@/lib/memory-filter'
import { repoListFrom, repoListOf, reposIn, reposWords } from '@/lib/repo-filter'
import { rowLineFrom } from '@/lib/rows'
import { useNow } from '@/lib/time'
import { cn } from '@/lib/utils'

/** The memory page's search params, each optional, so a link to the page names none. */
interface MemorySearch {
    q?: string | undefined
    repo?: string | undefined
    show?: MemoryShow | undefined
    history?: true | undefined
}

/**
 * Agent memory (DESIGN §28), what waits on the operator first: the proposals, then the lessons under the band that says
 * what reads them, then the tickets with notes in force, each opening to its notes. Every list scrolls in its panel, so
 * a busy workspace's thousands of notes and hundreds of lessons keep the page in reach. A proposal is promoted or
 * rejected, and a lesson renewed or forgotten, from its row, as `canopy memory` does, while `memory.proposals` is on
 * (ROADMAP M52). What every run is served of the lessons is folded under them, since it is the prompt's, not a queue.
 * Under every panel, `canopy memory purge`, the CLI's alone, copies.
 * `?q=` keeps what holds every word, `?repo=` the proposals and lessons for its repositories' runs, and `?show=` the
 * lessons that stand so, over what the page already read; `?history=true` reads and lists the latest proposals and
 * lessons no longer pending or in force too.
 */
export const Route = createFileRoute('/memory')({
    // Typed search params, as the tickets page's: every key returned, undefined when the page does not offer it.
    validateSearch: (search: Record<string, unknown>): MemorySearch => ({
        q: memoryQueryOf(search['q']),
        repo: repoListOf(search['repo']),
        show: memoryShowOf(search['show']),
        history: search['history'] === true ? true : undefined,
    }),
    component: MemoryPage,
})

function MemoryPage() {
    const { history } = Route.useSearch()
    const client = useQueryClient()
    // One read or the other: the history adds the past to what the page always reads. Each shows the other's while it
    // is read, so turning the history on or off keeps the page, and the rows opened on it, where they are.
    const now = useQuery({
        ...memoryQuery,
        enabled: history !== true,
        placeholderData: () => client.getQueryData(memoryHistoryQuery.queryKey),
    })
    const withPast = useQuery({
        ...memoryHistoryQuery,
        enabled: history === true,
        placeholderData: () => client.getQueryData(memoryQuery.queryKey),
    })
    const query = history === true ? withPast : now
    const { data } = query
    return (
        <>
            <PageHeader title="Memory">
                What workers learned, the proposals waiting on you, and the lessons you promoted. Decide them here or
                with <Code>canopy memory</Code>.
            </PageHeader>
            {data === undefined ? (
                <Panel>
                    <PanelLoading query={query} className="min-h-72" />
                </Panel>
            ) : data.state === null ? (
                <Panel>
                    <Empty size="panel">
                        memory is off now: set <Code>[memory]</Code> to record or use
                    </Empty>
                </Panel>
            ) : (
                <Tiers overview={data} state={data.state} pastRead={!withPast.isPlaceholderData} />
            )}
            {/* Under every panel, and with memory off too, when what a trial wrote is what is left to clear. */}
            {data !== undefined && <MemoryPurge />}
        </>
    )
}

/**
 * Every tier that is on, under the filter. `pastRead` is false while the history is still read, with what the page read
 * without it shown in its place: the past sections then hold a skeleton rather than say there is none.
 */
function Tiers({ overview, state, pastRead }: { overview: MemoryOverview; state: MemoryState; pastRead: boolean }) {
    const { tickets, proposals, lessons, lessons_digest: digest } = overview
    const acting = state.lessons.mode !== 'off'
    const modes = { ticket_notes: state.ticket_notes.mode, lessons: state.lessons.mode }
    const search = Route.useSearch()
    const filter: MemoryFilter = { q: search.q, repo: search.repo, show: search.show }
    const now = useNow()
    const shownProposals = proposals.filter((p) => memoryShown(p.entry, { ...filter, show: undefined }, now, modes))
    const shownLessons = lessons.filter((m) => memoryShown(m, filter, now, modes))
    const shownTickets = tickets.filter((t) => ticketNotesShown(t, filter.q))
    const unshown = { ...filter, show: undefined }
    const pastProposals = overview.past_proposals.filter((m) => memoryShown(m, unshown, now, modes))
    const pastLessons = overview.past_lessons.filter((m) => memoryShown(m, unshown, now, modes))
    const history = search.history === true
    // A panel's past: not shown without the history, null while it is read.
    function pastOf(entries: MemoryEntry[]): MemoryEntry[] | null | undefined {
        return history ? (pastRead ? entries : null) : undefined
    }
    // What notes say is searched on the server, as `canopy memory search`: the page holds their tickets' counts only.
    const searched = useQuery({ ...memorySearchQuery(filter.q ?? ''), enabled: filter.q !== undefined })
    const notesFound =
        filter.q === undefined
            ? undefined
            : (searched.data?.entries ?? []).filter((m) => m.scope === 'ticket' && m.status === 'active')
    return (
        <>
            <FilterBar repos={overview.repos} />
            {/* Wide, the tickets with notes sit beside the queue, last as when narrow, in the width their opened notes'
                columns need; only from 120rem, where the queue beside them still keeps a proposal's verbs on one line.
                Narrower, they stack under it, and the queue has the page's width. */}
            <div
                className={cn(
                    'stagger flex flex-col gap-6',
                    // Two columns only while both tiers show a panel: with one off, the other has the width alone.
                    acting &&
                        state.ticket_notes.mode !== 'off' && [
                            'min-[120rem]:grid min-[120rem]:items-start',
                            'min-[120rem]:grid-cols-[minmax(0,1fr)_minmax(0,34rem)]',
                        ],
                )}
            >
                {/* A tier that is off shows no panel: the page holds what is on (DESIGN §28). */}
                {acting && (
                    <div className="flex flex-col gap-6">
                        <Proposals
                            proposals={shownProposals}
                            total={proposals.length}
                            filter={filter}
                            acting={acting}
                            past={pastOf(pastProposals)}
                        />
                        <Lessons
                            lessons={shownLessons}
                            total={lessons.length}
                            filter={filter}
                            digest={digest}
                            tier={state.lessons}
                            acting={acting}
                            modes={modes}
                            past={pastOf(pastLessons)}
                        />
                    </div>
                )}
                {state.ticket_notes.mode !== 'off' && (
                    <TicketNotesPanel
                        tickets={shownTickets}
                        total={tickets.length}
                        filter={filter}
                        tier={state.ticket_notes}
                        promote={acting}
                        modes={modes}
                        found={notesFound}
                    />
                )}
            </div>
        </>
    )
}

/**
 * The proposals waiting on the operator, oldest first, each with where it came from and its verbs. None reaches a run
 * until it is promoted, at any mode, so the panel says that rather than the tier's band, which heads the lessons. Its
 * count wears `status-blocked` while one waits, as the nav's does.
 */
function Proposals({
    proposals,
    total,
    filter,
    acting,
    past,
}: {
    proposals: MemoryProposal[]
    total: number
    filter: MemoryFilter
    acting: boolean
    past: MemoryEntry[] | null | undefined
}) {
    const order = useListOrder('memory-proposals')
    const filtered = filter.q !== undefined || filter.repo !== undefined
    // What a verb did: its row leaves the list once it is done, so it is said under the panel's header.
    const [said, setSaid] = useState<string | null>(null)
    const facts = new Map(proposals.map((p) => [p.entry.id, <ProposalFacts key={p.entry.id} proposal={p} />]))
    const acted = acting ? proposals : []
    const below = new Map(
        acted.map((p) => [p.entry.id, <ProposalActions key={p.entry.id} proposal={p.entry} onSaid={setSaid} />]),
    )
    return (
        <Panel data-testid="memory-proposals">
            <PanelHeader label="Proposals">
                <span className="flex items-center gap-x-3">
                    {proposals.length > 1 && <OrderToggle list="memory-proposals" />}
                    <span
                        className={cn('readout text-xs', total > 0 ? 'text-status-blocked' : 'text-muted-foreground')}
                        data-testid="memory-proposals-count"
                    >
                        {shownCount(proposals.length, total, filtered)}
                    </span>
                </span>
            </PanelHeader>
            <p className="border-b px-3 py-2 text-sm text-muted-foreground">
                What workers proposed. None reaches a run until you promote it.
            </p>
            <MemorySaid said={said} className="border-b px-3 py-2" />
            {proposals.length === 0 && total > 0 ? (
                <Empty>no proposals{filterWords(filter)}</Empty>
            ) : proposals.length === 0 ? (
                // Cleared from this page just now: the one queue memory has is empty, and that is worth a word.
                <Empty className={cn(said !== null && 'text-accent')}>
                    {said === null ? 'no proposals wait on you now' : 'all decided: no proposal waits on you'}
                </Empty>
            ) : (
                // Up to 20 wait at once (MAX_PENDING), each with its verbs: past the panel's height they scroll in it,
                // so the lessons under them stay in reach.
                <PanelScroll label="Proposals">
                    <MemoryRows
                        entries={ordered('memory-proposals', order, proposals).map((p) => p.entry)}
                        ticket
                        facts={facts}
                        below={below}
                        lapses={new Map(proposals.map((p) => [p.entry.id, p.expires_at]))}
                    />
                </PanelScroll>
            )}
            {past !== undefined && <Past label="Decided" entries={past} ticket none="no proposal decided yet" />}
        </Panel>
    )
}

/**
 * The lessons the operator promoted, under the band that says whether runs read them: the pinned ones first, under a
 * heading of their own, as runs are served them; then the rest, in each those a run reported wrong first, then by
 * review date (the server's order). What every run is served of them opens under the list.
 */
function Lessons({
    lessons,
    total,
    filter,
    digest,
    tier,
    acting,
    modes,
    past,
}: {
    lessons: MemoryEntry[]
    total: number
    filter: MemoryFilter
    digest: MemoryDigest | null
    tier: MemoryTier
    acting: boolean
    modes: TierModes
    past: MemoryEntry[] | null | undefined
}) {
    const [said, setSaid] = useState<string | null>(null)
    const below = new Map(
        acting ? lessons.map((m) => [m.id, <LessonActions key={m.id} lesson={m} onSaid={setSaid} />]) : [],
    )
    return (
        <Panel data-testid="memory-lessons">
            <PanelHeader label="Lessons">
                <span className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1">
                    {modes.lessons === 'use' && (
                        <nav aria-label="Filter lessons by where they stand" className="flex items-center gap-1">
                            <FilterLink change={{ show: undefined }} selected={filter.show === undefined}>
                                all
                            </FilterLink>
                            {MEMORY_SHOWS.map((s) => (
                                <FilterLink key={s} change={{ show: s }} selected={filter.show === s}>
                                    <RunDot state={s === 'wrong' ? 'failed' : 'blocked'} />
                                    {s}
                                </FilterLink>
                            ))}
                        </nav>
                    )}
                    <span className="readout text-xs text-muted-foreground" data-testid="memory-lessons-count">
                        {shownCount(lessons.length, total, isFiltered(filter))}
                    </span>
                </span>
            </PanelHeader>
            <MemoryBand tier={tier} name="lessons" />
            <MemorySaid said={said} className="border-b px-3 py-2" />
            {lessons.length === 0 && total > 0 ? (
                <Empty>
                    no {filter.show === undefined ? '' : `${filter.show} `}lessons{filterWords(filter)}
                </Empty>
            ) : lessons.length === 0 ? (
                <Empty>no lessons yet: promote a proposal above, or a ticket&apos;s note from its page</Empty>
            ) : (
                <PanelScroll label="Lessons">
                    {lessonGroups(lessons).map((group) => (
                        // Named only while headed: alone, it is the whole list, which the scroller names.
                        <section
                            key={group.label}
                            aria-label={group.pinned === undefined ? undefined : group.label}
                            className="not-first:border-t"
                        >
                            {group.pinned !== undefined && (
                                <LessonsHeading
                                    label={group.label}
                                    pinned={group.pinned}
                                    count={group.entries.length}
                                />
                            )}
                            {/* The proposals' columns, the ticket's left empty, so key and text line up down the
                                page. */}
                            <MemoryRows
                                entries={group.entries}
                                across
                                digest={digest}
                                below={below}
                                modes={modes}
                                onVersionSaid={acting ? setSaid : undefined}
                            />
                        </section>
                    ))}
                </PanelScroll>
            )}
            {past !== undefined && <Past label="Retired" entries={past} none="no lesson replaced or forgotten yet" />}
            {digest !== null && <MemoryDigestFold digest={digest} who="every run" />}
        </Panel>
    )
}

/**
 * A group's heading in the Lessons panel: its name and count, and what being in it means for a run and for review.
 * The pinned group's carries a filled pin in the foreground, so it is seen at a glance over the muted labels.
 */
function LessonsHeading({ label, pinned, count }: { label: string; pinned: boolean; count: number }) {
    return (
        <h3 className="flex items-center gap-1.5 border-b px-3 py-1.5" data-testid="memory-lessons-group">
            {pinned && <Pin aria-hidden className="size-3 fill-current text-foreground" />}
            <span className={cn('panel-label', pinned && 'text-foreground')}>{label}</span>
            <span className="readout text-2xs text-muted-foreground">{count}</span>
            <span className="ml-auto text-2xs text-muted-foreground">
                {pinned ? 'served first, never due' : 'wrong first, then by review date'}
            </span>
        </h3>
    )
}

/**
 * A panel's history, under what is pending or in force, while `?history=true`: its latest memories no longer either,
 * each under the standing and reason the journal gives it, with no verbs, since nothing is left to decide; a row's
 * skeleton while `entries` is null, still being read.
 */
function Past({
    label,
    entries,
    ticket = false,
    none,
}: {
    label: string
    entries: MemoryEntry[] | null
    ticket?: boolean
    none: string
}) {
    return (
        <section aria-label={label} className="border-t" data-testid={`memory-past-${label.toLowerCase()}`}>
            <h3 className="px-3 pt-2 panel-label">{label}</h3>
            {entries === null ? (
                <PanelSkeleton rows={1} />
            ) : entries.length === 0 ? (
                <Empty>{none}</Empty>
            ) : (
                <PanelScroll label={label}>
                    <MemoryRows entries={entries} ticket={ticket} across={!ticket} />
                </PanelScroll>
            )}
        </section>
    )
}

/**
 * The toggle that shows each panel's history, kept in `?history=true`, as a filter chip is: on, the page reads the
 * latest memories no longer pending or in force, and lists them under the rest. One, in the filter bar, since it acts
 * on every panel.
 */
function HistoryToggle() {
    const search = Route.useSearch()
    const on = search.history === true
    return (
        <Link
            to="/memory"
            search={{ ...search, history: on ? undefined : true }}
            aria-pressed={on}
            data-selected={on}
            title={on ? 'Hide what is no longer pending or in force' : 'Show what is no longer pending or in force'}
            className={cn(
                'flex h-6 items-center gap-1.5 rounded-sm px-2 font-mono text-xs text-muted-foreground',
                'hover:bg-surface-raised hover:text-foreground',
                'data-[selected=true]:bg-accent/16 data-[selected=true]:text-foreground',
            )}
        >
            <History aria-hidden className="size-3.5" />
            history
        </Link>
    )
}

/**
 * The tickets with notes in force, a row each, under the tier's band. Its header counts the rows, the tickets, and the
 * notes they hold beside them, since a row opens to several, or while the filter has words the notes found that hold
 * them. Each opened note is forgotten from its row, and, while
 * lessons are on (`promote`), promoted; what that did is said under the band. While the filter has words, `found` is
 * the notes in force whose key or text holds every one, as the rows above hold them, found by the function
 * `canopy memory search` runs, listed under the tickets.
 */
function TicketNotesPanel({
    tickets,
    total,
    filter,
    tier,
    promote,
    modes,
    found,
}: {
    tickets: TicketNotes[]
    total: number
    filter: MemoryFilter
    tier: MemoryTier
    promote: boolean
    modes: TierModes
    found: MemoryEntry[] | undefined
}) {
    const [said, setSaid] = useState<string | null>(null)
    const notes = tickets.reduce((sum, t) => sum + t.count, 0)
    const ticketsWord = total === 1 ? 'ticket' : 'tickets'
    const notesWord = notes === 1 ? 'note' : 'notes'
    const shown = shownCount(tickets.length, total, filter.q !== undefined)
    // While searching, the notes counted are those found, which the list under the tickets shows.
    const notesCount = found === undefined ? `${notes} ${notesWord}` : foundCount(found.length)
    const ticketsCount = `${shown} ${ticketsWord} · ${notesCount}`
    const order = useListOrder('memory-tickets')
    const filteredOut = tickets.length === 0 && total > 0
    const notesFound = found !== undefined && found.length > 0
    return (
        <Panel data-testid="memory-notes">
            <PanelHeader label="Ticket notes">
                <span className="flex items-center gap-x-3">
                    {tickets.length > 1 && <OrderToggle list="memory-tickets" />}
                    <span className="readout text-xs text-muted-foreground" data-testid="memory-notes-count">
                        {ticketsCount}
                    </span>
                </span>
            </PanelHeader>
            <MemoryBand tier={tier} name="ticket notes" />
            <MemorySaid said={said} className="border-b px-3 py-2" />
            {filter.repo !== undefined && (
                <p className="border-b px-3 py-2 text-xs text-muted-foreground" data-testid="memory-notes-every-repo">
                    Not narrowed by repository: a ticket&apos;s notes are read by its own runs, in any repository.
                </p>
            )}
            {filteredOut ? (
                // The notes found below may still hold the words; only when none does is the panel empty.
                notesFound ? null : (
                    <Empty>
                        no note says “{filter.q?.trim()}”, and no ticket with notes has it in its key or title
                    </Empty>
                )
            ) : tickets.length === 0 ? (
                <Empty>no notes in force now: a ticket&apos;s runs write them as they end</Empty>
            ) : (
                <PanelScroll label="Ticket notes">
                    <ul className="divide-y">
                        {ordered('memory-tickets', order, tickets).map((t) => (
                            <TicketNotesRow
                                key={t.ticket_key}
                                notes={t}
                                onSaid={setSaid}
                                promote={promote}
                                modes={modes}
                            />
                        ))}
                    </ul>
                </PanelScroll>
            )}
            {notesFound && (
                <section aria-label="Notes that say it" className="border-t" data-testid="memory-notes-found">
                    <h3 className="flex items-baseline gap-2 px-3 pt-2">
                        <span className="panel-label">Notes that say it</span>
                        {found.length >= MEMORY_FOUND_MAX && (
                            <span className="text-xs text-muted-foreground" data-testid="memory-notes-found-capped">
                                the best {MEMORY_FOUND_MAX}: another word narrows them
                            </span>
                        )}
                    </h3>
                    <PanelScroll label="Notes that say it">
                        <MemoryRows
                            entries={found}
                            ticket
                            below={
                                new Map(
                                    found.map((n) => [
                                        n.id,
                                        <NoteActions key={n.id} note={n} promote={promote} onSaid={setSaid} />,
                                    ]),
                                )
                            }
                            modes={modes}
                            onVersionSaid={setSaid}
                        />
                    </PanelScroll>
                </section>
            )}
        </Panel>
    )
}

/**
 * The page's filter, over every panel: a field for words, kept in `?q=` as the tickets page keeps its own, narrowing
 * as the operator types and replacing the history entry; a picker of the workspace's repositories, kept in `?repo=`
 * and replacing it too (`RepoFilter`); and the toggle that lists what is no longer pending or in force.
 */
function FilterBar({ repos }: { repos: string[] }) {
    const filter = Route.useSearch()
    const navigate = Route.useNavigate()
    const [value, setValue] = useState(filter.q ?? '')
    // What `?q=` was when the field last looked, so a change from outside it shows there.
    const [seen, setSeen] = useState(filter.q)
    if (filter.q !== seen) {
        setSeen(filter.q)
        setValue(filter.q ?? '')
    }

    const chosen = reposIn(filter.repo)
    // Those chosen that the workspace map no longer names are offered too, so each can be taken away.
    const offered = [...new Set([...repos, ...chosen])].toSorted()

    function find(text: string) {
        const q = memoryQueryOf(text)
        setValue(text)
        setSeen(q)
        void navigate({ search: (prev) => ({ ...prev, q }), replace: true })
    }

    return (
        <search className="flex flex-wrap items-center gap-x-3 gap-y-2" data-testid="memory-filter">
            <SearchField
                aria-label="Filter memory by key, text, ticket, or repository"
                placeholder="Filter by key, text, ticket, or repository"
                maxLength={MEMORY_QUERY_MAX}
                value={value}
                onChange={(event) => find(event.target.value)}
                onKeyDown={(event) => {
                    if (event.key === 'Escape') {
                        event.currentTarget.blur()
                    }
                }}
                onClear={() => find('')}
                clearLabel="Clear the filter"
                className="min-w-64 flex-1 basis-80"
            />
            {offered.length > 1 && (
                <RepoFilter
                    repos={offered}
                    chosen={chosen}
                    onChoose={(next) =>
                        void navigate({ search: (prev) => ({ ...prev, repo: repoListFrom(next) }), replace: true })
                    }
                />
            )}
            <HistoryToggle />
        </search>
    )
}

/** A filter chip, selected when the validated search matches it; following it changes only what `change` names. */
function FilterLink({ change, selected, children }: { change: MemorySearch; selected: boolean; children: ReactNode }) {
    const search = Route.useSearch()
    return (
        <Link
            to="/memory"
            search={{ ...search, ...change }}
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

/** Whether any filter is set. */
function isFiltered(filter: MemoryFilter): boolean {
    return filter.q !== undefined || filter.repo !== undefined || filter.show !== undefined
}

/** What a panel's empty list says of the filter that left nothing: ` with “billing” for web`. */
function filterWords(filter: MemoryFilter): string {
    const q = filter.q === undefined ? '' : ` with “${filter.q.trim()}”`
    const repo = filter.repo === undefined ? '' : ` for ${reposWords(filter.repo)}`
    return `${q}${repo}`
}

/**
 * A ticket with notes in force: its key, how many, its title, how runs used them, and when the newest was written.
 * Its notes open under it, read only once opened (closed, the content is not mounted), so a workspace of many tickets
 * sends their counts and not every note.
 */
function TicketNotesRow({
    notes,
    onSaid,
    promote,
    modes,
}: {
    notes: TicketNotes
    onSaid: (said: string) => void
    promote: boolean
    modes: TierModes
}) {
    const [open, setOpen] = useState(false)
    const what = `${notes.count} ${notes.count === 1 ? 'note' : 'notes'}`
    return (
        <Collapsible asChild open={open} onOpenChange={setOpen}>
            <ListRow kind="memory-ticket" data-testid={`memory-ticket-${notes.ticket_key}`}>
                <TicketLink ticketKey={notes.ticket_key} />
                <span className="min-w-0">
                    {/* No taller than a line of text, its chevron in line with the key beside it. */}
                    <Disclosure open={open} what={what} className="-my-1 -ml-2" />
                </span>
                <TicketTitle title={notes.title} />
                <span className="truncate text-right text-xs text-muted-foreground">{ticketNotesUsedText(notes)}</span>
                <Age at={notes.latest_at} variant="ago" className="text-right" />
                <CollapsibleContent className={cn('-mx-3 -mb-2.5 border-t bg-surface-raised/40', rowLineFrom('key'))}>
                    <OpenNotes ticketKey={notes.ticket_key} onSaid={onSaid} promote={promote} modes={modes} />
                </CollapsibleContent>
            </ListRow>
        </Collapsible>
    )
}

/**
 * A ticket's notes in force, under its row: each marked when the cap leaves it out of its next run's prompt, each with
 * Forget, and with `promote`, while lessons are on, Promote.
 */
function OpenNotes({
    ticketKey,
    onSaid,
    promote,
    modes,
}: {
    ticketKey: string
    onSaid: (said: string) => void
    promote: boolean
    modes: TierModes
}) {
    const { data } = useQuery(ticketMemoryQuery(ticketKey))
    if (data === undefined) {
        return <PanelSkeleton rows={1} />
    }
    const inForce = data.notes.filter((n) => n.status === 'active')
    if (inForce.length === 0) {
        return <Empty>no notes in force now: its page lists the ones before</Empty>
    }
    const below = new Map(
        inForce.map((n) => [n.id, <NoteActions key={n.id} note={n} promote={promote} onSaid={onSaid} />]),
    )
    return (
        <MemoryRows entries={inForce} across digest={data.digest} below={below} modes={modes} onVersionSaid={onSaid} />
    )
}
