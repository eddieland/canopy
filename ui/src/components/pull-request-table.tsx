import type { ReactNode } from 'react'

import { None } from '@/components/none'
import { PullRequestLink } from '@/components/pull-request-link'
import { ReportTable } from '@/components/report-table'
import type { ReportColumn } from '@/components/report-table'
import { Word } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { phaseMeaning } from '@/lib/meanings'
import { NO_TICKET } from '@/lib/words'

/** A PR as a report's per-PR table lists it: the PR, and the ticket and phase of the unit that holds it. */
export interface PullRequestRow {
    /** The PR. */
    url: string
    /** The ticket that owns it; null for a PR canopy only reviewed. */
    ticket_key?: string | null
    /** Its unit's phase; null for a PR no unit of the loop's has. */
    phase?: string | null
}

/** One of a per-PR table's figures, after the PR and its ticket: right aligned, in the readout's type. */
export interface PullRequestColumn<T> {
    /** What it counts, its cells' key. */
    key: string
    /** Its head. */
    label: string
    /** What it counts, in its head's tip. */
    hint?: string
    /** A row's figure. */
    cell: (row: T) => ReactNode
    /** A row's figure in its tip, where the figure sums or cuts something. */
    title?: (row: T) => string
    /** Whether the cell is muted, as a secondary figure is. */
    muted?: boolean
    /** A row's figure as a share of the column's largest, 0 to 100, drawn as a bar after it (`CellBar`). */
    bar?: (row: T) => number
}

/**
 * A report's table of PRs (ui/DESIGN.md, "A table of PRs"), a `ReportTable` with a row each: the PR, linked, with its
 * unit's phase beside it; its ticket, or none for a PR canopy only reviewed; then each of `columns`. Named `label` for
 * a screen reader. The table's test id is `testId`'s, then `-pull-request-table`; each row's, then `-pull-request`. A
 * page shows its own `Empty` in its place when it has no rows.
 */
export function PullRequestTable<T extends PullRequestRow>({
    rows,
    columns,
    label,
    testId,
}: {
    rows: readonly T[]
    columns: readonly PullRequestColumn<T>[]
    label: string
    testId: string
}) {
    const all: ReportColumn<T>[] = [
        ...leadingColumns<T>(),
        ...columns.map((column): ReportColumn<T> => ({
            key: column.key,
            kind: column.bar === undefined ? 'figure' : 'bar',
            label: column.label,
            hint: column.hint,
            cell: column.cell,
            tip: column.title,
            muted: column.muted,
            bar: column.bar,
        })),
    ]
    return (
        <ReportTable
            rows={rows}
            columns={all}
            rowKey={(pr) => pr.url}
            label={label}
            testId={`${testId}-pull-request-table`}
            rowTestId={`${testId}-pull-request`}
        />
    )
}

/** The columns every per-PR table opens with: the PR and its phase, then its ticket. */
function leadingColumns<T extends PullRequestRow>(): ReportColumn<T>[] {
    return [
        { key: 'pull-request', kind: 'free', label: 'pull request', cell: (pr) => <PullRequestCell pr={pr} /> },
        { key: 'ticket', kind: 'word', label: 'ticket', cell: (pr) => <TicketCell ticketKey={pr.ticket_key} /> },
    ]
}

function PullRequestCell({ pr }: { pr: PullRequestRow }) {
    return (
        <span className="flex min-w-0 items-center gap-2">
            <PullRequestLink url={pr.url} className="min-w-0" />
            {pr.phase !== null && pr.phase !== undefined && (
                <Word word={pr.phase} meaning={phaseMeaning(pr.phase)} className="truncate text-muted-foreground" />
            )}
        </span>
    )
}

function TicketCell({ ticketKey }: { ticketKey: string | null | undefined }) {
    return ticketKey === null || ticketKey === undefined ? (
        <None reason={NO_TICKET} brief className="font-mono text-xs" />
    ) : (
        <TicketLink ticketKey={ticketKey} />
    )
}
