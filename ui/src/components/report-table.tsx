import type { ReactNode } from 'react'

import { CellBar, CellBarHead } from '@/components/cell-bar'
import { PanelScroll } from '@/components/panel'
import { Hinted, Tipped } from '@/components/tip'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'

/**
 * What a column of a `ReportTable` holds, which sets how its head and its cells sit (ui/DESIGN.md, "A table of
 * figures"): `name`, what the row names, as its row head; `free`, text that wants the room, which takes what the
 * other columns leave and is cut to fit; `figure`, a readout, right-aligned, never wrapped; `bar`, a figure with a bar
 * of its share after it (`CellBar`); `word`, a short word, a link, or a chip, left-aligned, never wrapped.
 */
export type ReportColumnKind = 'name' | 'free' | 'figure' | 'bar' | 'word'

/** One of a `ReportTable`'s columns. */
export interface ReportColumn<T> {
    /** What it holds, its cells' key. */
    key: string
    /** What it holds, which sets how it sits. */
    kind: ReportColumnKind
    /** Its head. */
    label: ReactNode
    /** What it counts, in its head's tip. */
    hint?: string
    /** A row's cell. */
    cell: (row: T) => ReactNode
    /** A row's cell in its tip, where the cell sums or cuts something. */
    tip?: (row: T) => string | undefined
    /** Whether its cells are muted, as a secondary figure is. */
    muted?: boolean
    /** A row's own classes for its cell, such as a failure's color. */
    tone?: (row: T) => string | false | undefined
    /** For a `bar`: a row's figure as a share of the column's largest, 0 to 100 (`barPercent`). */
    bar?: (row: T) => number
    /** For a `bar`: the bar's fill, `muted-foreground` unless the series has its own. */
    fill?: string
}

// The column names stick inside the padded scrolling region. A sticky head sticks inside the region's padding, so the
// rows scrolling under it would show in a strip above it: the region's top padding is the head's cells' instead.
const PADDED_HEAD = 'sticky top-0 bg-surface [&_th]:pt-3'

// How a head sits, by its column's kind: over the text it names, so a figure's head is right-aligned.
const HEAD_ALIGN: Record<Exclude<ReportColumnKind, 'bar'>, string> = {
    name: 'text-left',
    free: 'text-left',
    figure: 'text-right',
    word: 'text-left',
}

// How a cell sits, by its column's kind. A free column takes the room the others leave (`w-full`), and its content
// is cut to fit rather than widen the table (`max-w-0`).
const CELL: Record<Exclude<ReportColumnKind, 'bar'>, string> = {
    name: 'text-left whitespace-nowrap',
    free: 'w-full max-w-0 text-left',
    figure: 'readout text-right whitespace-nowrap',
    word: 'text-left whitespace-nowrap',
}

/**
 * A report's table (ui/DESIGN.md, "A table of figures"), one row of `rows` each, in `columns`: the first column is the
 * row's head, so it names the row (a `name`, `free`, or `word` column), never a figure or a bar. It scrolls in its
 * panel under a sticky head, named `label` for a screen reader, in a region of `className` (its height, `max-h-96`
 * unless given). `rowKey` keys a row; the table's test id is `testId`, each row's
 * `rowTestId`. A page shows its own `Empty` in its place when it has no rows.
 */
export function ReportTable<T>({
    rows,
    columns,
    rowKey,
    label,
    className,
    testId,
    rowTestId,
}: {
    rows: readonly T[]
    columns: readonly ReportColumn<T>[]
    rowKey: (row: T) => string
    label: string
    className?: string
    testId?: string
    rowTestId?: string
}) {
    return (
        <PanelScroll label={label} className={cn('max-h-96 px-3 pb-3', className)}>
            {/* A free column takes the panel's slack, which a table has to give only at the panel's width. */}
            <Table className={cn(columns.some((c) => c.kind === 'free') && 'w-full')} data-testid={testId}>
                <TableHeader className={PADDED_HEAD}>
                    <TableRow>
                        {columns.map((column, i) => (
                            <ColumnHead key={column.key} column={column} first={i === 0} />
                        ))}
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {rows.map((row) => (
                        <TableRow key={rowKey(row)} data-testid={rowTestId}>
                            {columns.map((column, i) => (
                                <ColumnCell key={column.key} column={column} row={row} first={i === 0} />
                            ))}
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </PanelScroll>
    )
}

function ColumnHead<T>({ column, first }: { column: ReportColumn<T>; first: boolean }) {
    const name = <Hinted hint={column.hint}>{column.label}</Hinted>
    if (column.kind === 'bar') {
        return <CellBarHead>{name}</CellBarHead>
    }
    return <TableHead className={cn(HEAD_ALIGN[column.kind], !first && 'pl-3')}>{name}</TableHead>
}

function ColumnCell<T>({ column, row, first }: { column: ReportColumn<T>; row: T; first: boolean }) {
    const tone = cn(column.muted === true && 'text-muted-foreground', column.tone?.(row))
    const content = <Tipped fact={column.tip?.(row)}>{column.cell(row)}</Tipped>
    if (column.kind === 'bar') {
        return (
            <CellBar percent={column.bar?.(row) ?? 0} fill={column.fill} className={cn('readout', tone)}>
                {content}
            </CellBar>
        )
    }
    const className = cn(CELL[column.kind], !first && 'pl-3', tone)
    return first ? (
        <th scope="row" className={cn('py-0.5 font-normal', className)}>
            {content}
        </th>
    ) : (
        <TableCell className={className}>{content}</TableCell>
    )
}
