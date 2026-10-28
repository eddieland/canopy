import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { ticketsQuery } from '@/api/queries'
import type { TicketSummary } from '@/api/types'
import { Age } from '@/components/age'
import { FilterField } from '@/components/filter-field'
import { OrderToggle } from '@/components/order-toggle'
import { Empty, PageHeader, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { ListRow } from '@/components/rows'
import { StartTicket } from '@/components/start-ticket'
import { Chip, RunDot } from '@/components/status'
import { TicketBoard } from '@/components/ticket-board'
import { TicketLink } from '@/components/ticket-link'
import { TicketState } from '@/components/ticket-state'
import { TicketTitle } from '@/components/ticket-title'
import { Tip } from '@/components/tip'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { ordered, useListOrder } from '@/lib/list-order'
import { phaseMeaning } from '@/lib/meanings'
import { phaseLabel, phaseWord } from '@/lib/phase'
import {
    TICKET_QUERY_MAX,
    TICKET_SHOW_LABEL,
    TICKET_SHOWS,
    ticketQueryOf,
    ticketShowOf,
    ticketShown,
} from '@/lib/ticket-filter'
import type { TicketShow } from '@/lib/ticket-filter'
import { cn } from '@/lib/utils'

/** How the page lays the tickets out: rows in a list, the default, or a board of a column per stage. */
const VIEWS = ['list', 'board'] as const

interface TicketsSearch {
    show?: TicketShow | undefined
    q?: string | undefined
    view?: 'board' | undefined
}

/**
 * Every ticket canopy has worked or been asked to, most recent activity first, and a form to start one. `?show=` keeps
 * the tickets standing there (open, working, waiting on you, blocked, done), and `?q=` those whose key or title holds
 * every word. `?view=board` lays them out as a board, a column per stage (`TicketBoard`), under the same filters.
 */
export const Route = createFileRoute('/tickets/')({
    // Typed search params, as the runs page's: every key returned, undefined when the page does not offer it.
    validateSearch: (search: Record<string, unknown>): TicketsSearch => ({
        show: ticketShowOf(search['show']),
        q: ticketQueryOf(search['q']),
        view: search['view'] === 'board' ? 'board' : undefined,
    }),
    component: TicketsPage,
})

function TicketsPage() {
    const { show, q, view } = Route.useSearch()
    const navigate = Route.useNavigate()
    const { data } = useQuery(ticketsQuery)
    const shown = data?.filter((ticket) => ticketShown(ticket, show, q))
    const filtered = show !== undefined || q !== undefined
    const order = useListOrder('tickets')
    return (
        <>
            <PageHeader title="Tickets">
                Every ticket canopy has worked or been asked to, most recent activity first.
            </PageHeader>
            <Panel>
                <PanelHeader label="Start a ticket" />
                <StartTicket />
            </Panel>
            <Panel>
                <PanelHeader label="Tickets">
                    <span className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1">
                        <ToggleGroup
                            type="single"
                            value={view ?? 'list'}
                            aria-label="Lay out as"
                            onValueChange={(value) => {
                                // Pressing the view shown turns it off: keep it. The list, the default, has no search.
                                const picked = VIEWS.find((v) => v === value)
                                if (picked !== undefined) {
                                    void navigate({
                                        search: (prev) => ({ ...prev, view: picked === 'board' ? 'board' : undefined }),
                                    })
                                }
                            }}
                        >
                            {VIEWS.map((v) => (
                                <ToggleGroupItem key={v} value={v}>
                                    {v}
                                </ToggleGroupItem>
                            ))}
                        </ToggleGroup>
                        <nav aria-label="Filter by where it stands" className="flex flex-wrap items-center gap-1">
                            <FilterLink show={undefined}>all</FilterLink>
                            {TICKET_SHOWS.map((s) => (
                                <FilterLink key={s} show={s}>
                                    {s === 'working' && <RunDot state="running" />}
                                    {s === 'waiting' && <RunDot state="blocked" />}
                                    {TICKET_SHOW_LABEL[s]}
                                </FilterLink>
                            ))}
                        </nav>
                        {shown !== undefined && shown.length > 1 && <OrderToggle list="tickets" />}
                        <span className="readout text-xs text-muted-foreground" data-testid="tickets-count">
                            {countText(shown, data, filtered)}
                        </span>
                    </span>
                </PanelHeader>
                <TextFilter />
                {shown === undefined ? (
                    <PanelSkeleton className="min-h-72" />
                ) : data?.length === 0 ? (
                    <Empty size="panel">
                        no tickets yet: start one above, or give one the queue label in the tracker
                    </Empty>
                ) : shown.length === 0 ? (
                    <Empty size="panel">{emptyText(show, q)}</Empty>
                ) : view === 'board' ? (
                    <TicketBoard tickets={ordered('tickets', order, shown)} />
                ) : (
                    <ul className="divide-y" data-testid="tickets">
                        {ordered('tickets', order, shown).map((ticket) => (
                            <Row key={ticket.key} ticket={ticket} />
                        ))}
                    </ul>
                )}
            </Panel>
        </>
    )
}

/** How many tickets the list shows, and of how many when a filter left some out: `6 of 41`. */
function countText(shown: TicketSummary[] | undefined, data: TicketSummary[] | undefined, filtered: boolean) {
    if (shown === undefined || data === undefined) {
        return ''
    }
    return filtered ? `${shown.length} of ${data.length}` : String(data.length)
}

/** What the list says when its filters leave no ticket of the ones listed. */
function emptyText(show: TicketShow | undefined, q: string | undefined) {
    const which = show === undefined ? 'tickets' : show === 'waiting' ? 'tickets waiting on you' : `${show} tickets`
    return q === undefined ? `no ${which} now` : `no ${which} with “${q.trim()}” in the key or title`
}

/** A filter chip, selected when it matches the validated search: an unknown `?show=` selects `all`. It keeps `?q=`. */
function FilterLink({ show, children }: { show: TicketShow | undefined; children: ReactNode }) {
    const search = Route.useSearch()
    return (
        <Link
            to="/tickets"
            search={{ ...search, show }}
            data-selected={search.show === show}
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

/** The text filter, kept in `?q=` (`FilterField`). */
function TextFilter() {
    const { q } = Route.useSearch()
    const navigate = Route.useNavigate()
    return (
        <search className="border-b px-3 py-2">
            <FilterField
                q={q}
                queryOf={ticketQueryOf}
                onFilter={(query) => void navigate({ search: (prev) => ({ ...prev, q: query }), replace: true })}
                label="Filter tickets by key or title"
                placeholder="Filter by key or title"
                maxLength={TICKET_QUERY_MAX}
            />
        </search>
    )
}

/**
 * A ticket: where it stands (its run, waiting on you, done, or open), its key, its phase, public or private, its
 * title, and its age.
 */
function Row({ ticket }: { ticket: TicketSummary }) {
    return (
        <ListRow kind="ticket" data-testid={`ticket-${ticket.key}`}>
            <TicketState ticket={ticket} />
            <TicketLink ticketKey={ticket.key} className="truncate" />
            {/* Cut to fit, the whole in its tip in the CLI's spelling. */}
            <Tip fact={phaseWord(ticket)} mono detail={phaseMeaning(ticket.phase)}>
                <span className="truncate font-mono text-xs text-muted-foreground">{phaseLabel(ticket)}</span>
            </Tip>
            <span className="flex">
                <Chip>{ticket.private ? `private, ${ticket.start ?? ''}` : 'public'}</Chip>
            </span>
            <TicketTitle title={ticket.title} />
            <Age at={ticket.active_at} variant="ago" className="text-right" />
        </ListRow>
    )
}
