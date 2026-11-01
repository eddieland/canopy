import type { ReactNode } from 'react'

import { None } from '@/components/none'
import { PanelScroll } from '@/components/panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { Word } from '@/components/status'
import { TicketLink } from '@/components/ticket-link'
import { Hinted, Tipped } from '@/components/tip'
import { phaseMeaning } from '@/lib/meanings'
import { cn } from '@/lib/utils'
import { NO_TICKET } from '@/lib/words'

// The column names of a table in a padded scrolling region. A sticky head sticks inside the region's padding, so the
// rows scrolling under it would show in a strip above it: the region's top padding is the head's cells' instead.
const PADDED_HEAD = 'sticky top-0 bg-surface [&_th]:pt-3'

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
}

/**
 * A report's table of PRs (ui/DESIGN.md, "A table of figures"), one row each: the PR, linked, with its unit's phase
 * beside it; its ticket, or none for a PR canopy only reviewed; then each of `columns`. It scrolls in its panel under a
 * sticky head, named `label` for a screen reader. The table's test id is `testId`'s, then `-pull-request-table`; each
 * row's, then `-pull-request`. A page shows its own `Empty` in its place when it has no rows.
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
    return (
        <PanelScroll label={label} className="max-h-96 px-3 pb-3">
            <table className="w-full border-collapse text-sm" data-testid={`${testId}-pull-request-table`}>
                <thead className={PADDED_HEAD}>
                    <tr className="text-right">
                        <th className="panel-label pb-1.5 text-left font-normal">pull request</th>
                        <th className="panel-label pb-1.5 pl-3 text-left font-normal">ticket</th>
                        {columns.map((column) => (
                            <th key={column.key} className="panel-label pb-1.5 pl-3 font-normal whitespace-nowrap">
                                <Hinted hint={column.hint}>{column.label}</Hinted>
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody className="text-xs">
                    {rows.map((pr) => (
                        <tr key={pr.url} className="text-right" data-testid={`${testId}-pull-request`}>
                            <th scope="row" className="w-full max-w-0 py-0.5 text-left font-normal">
                                <span className="flex min-w-0 items-center gap-2">
                                    <PullRequestLink url={pr.url} className="min-w-0" />
                                    {pr.phase !== null && pr.phase !== undefined && (
                                        <Word
                                            word={pr.phase}
                                            meaning={phaseMeaning(pr.phase)}
                                            className="truncate text-muted-foreground"
                                        />
                                    )}
                                </span>
                            </th>
                            <td className="pl-3 text-left whitespace-nowrap">
                                {pr.ticket_key === null || pr.ticket_key === undefined ? (
                                    <None reason={NO_TICKET} brief className="font-mono text-xs" />
                                ) : (
                                    <TicketLink ticketKey={pr.ticket_key} />
                                )}
                            </td>
                            {columns.map((column) => (
                                <td
                                    key={column.key}
                                    className={cn('readout pl-3', column.muted === true && 'text-muted-foreground')}
                                >
                                    <Tipped fact={column.title?.(pr)}>{column.cell(pr)}</Tipped>
                                </td>
                            ))}
                        </tr>
                    ))}
                </tbody>
            </table>
        </PanelScroll>
    )
}
