import { Link } from '@tanstack/react-router'

import type { TicketSummary } from '@/api/types'
import { Age } from '@/components/age'
import { Chip } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { TicketState } from '@/components/ticket-state'
import { TicketTitle } from '@/components/ticket-title'
import { Tip } from '@/components/tip'
import { phaseLabel, phaseWord } from '@/lib/phase'
import {
    BOARD_COLUMN_HELP,
    BOARD_COLUMN_LABEL,
    BOARD_COLUMNS,
    boardOf,
    DONE_SHOWN,
    mostRecent,
} from '@/lib/ticket-board'
import type { BoardColumn } from '@/lib/ticket-board'

/**
 * The tickets as a board (`?view=board`): a column for each stage, left to right as a ticket moves (`boardColumn`),
 * each its count and its tickets as cards in the order given. Every column shows, an empty one saying so, so a stage
 * stays in its place. The done column shows its most recent `DONE_SHOWN`, in the order given, and links to the rest.
 * It only reads: a ticket moves when the loop moves it, never by a drag. Wider than the panel, it scrolls sideways
 * inside it.
 */
export function TicketBoard({ tickets }: { tickets: Iterable<TicketSummary> }) {
    const board = boardOf(tickets)
    return (
        <section
            aria-label="Tickets by stage"
            // A scrolling region takes focus so the keyboard can scroll it (axe's scrollable-region-focusable).
            // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex
            tabIndex={0}
            className="overflow-x-auto p-3 [scrollbar-width:thin] focus-visible:-outline-offset-2"
            data-testid="ticket-board"
        >
            <div className="grid auto-cols-[minmax(11rem,1fr)] grid-flow-col gap-3">
                {BOARD_COLUMNS.map((column) => (
                    <Column key={column} column={column} tickets={board[column]} />
                ))}
            </div>
        </section>
    )
}

/** One stage's column: its name and count, what it holds on the name's hover, then its cards. */
function Column({ column, tickets }: { column: BoardColumn; tickets: TicketSummary[] }) {
    const id = `board-${column}`
    const shown = column === 'done' ? mostRecent(tickets, DONE_SHOWN) : tickets
    const more = tickets.length - shown.length
    return (
        <section
            aria-labelledby={id}
            className="flex min-w-0 flex-col gap-2 rounded-md border bg-background p-2"
            data-testid={id}
        >
            <h3 id={id} className="flex items-baseline justify-between gap-2 px-1" title={BOARD_COLUMN_HELP[column]}>
                <span className="panel-label font-medium text-foreground">{BOARD_COLUMN_LABEL[column]}</span>
                <span className="readout text-xs text-muted-foreground">{tickets.length}</span>
            </h3>
            {tickets.length === 0 ? (
                <p className="px-1 text-xs text-muted-foreground">none</p>
            ) : (
                <ul className="flex flex-col gap-2">
                    {shown.map((ticket) => (
                        <Card key={ticket.key} ticket={ticket} />
                    ))}
                </ul>
            )}
            {more > 0 && (
                <Link
                    to="/tickets"
                    search={{ show: 'done' }}
                    className="px-1 font-mono text-xs text-accent underline-offset-4 hover:underline"
                >
                    {`+${more} more done`}
                </Link>
            )}
        </section>
    )
}

/**
 * A ticket on the board: its key and its age; its title; then where it stands, its phase, which says more than its
 * column does (`ci red` in CI), and `private` when it is.
 */
function Card({ ticket }: { ticket: TicketSummary }) {
    return (
        <li
            className="flex min-w-0 flex-col gap-1.5 rounded-sm border bg-surface px-2.5 py-2"
            data-testid={`ticket-${ticket.key}`}
        >
            <span className="flex min-w-0 items-center gap-2">
                <TicketLink ticketKey={ticket.key} />
                <Age at={ticket.active_at} variant="ago" className="ml-auto shrink-0 text-right" />
            </span>
            <TicketTitle title={ticket.title} />
            <span className="flex min-w-0 flex-wrap items-start gap-x-3 gap-y-1">
                <TicketState ticket={ticket} />
                <Tip fact={phaseWord(ticket)} mono>
                    <span className="min-w-0 truncate font-mono text-xs text-muted-foreground">
                        {phaseLabel(ticket)}
                    </span>
                </Tip>
                {ticket.private && <Chip>private</Chip>}
            </span>
        </li>
    )
}
