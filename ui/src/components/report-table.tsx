import type { ReactNode } from 'react'

import { CellBar, CellBarHead } from '@/components/cell-bar'
import { PanelScroll } from '@/components/panel'
import { Hinted, Tipped } from '@/components/tip'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'

/**
 * What a column of a `ReportTable` holds, which sets how its head and its cells sit (ui/DESIGN.md, "A table of
 * figures"): `name`, what the row names, as its row head; `free`, text that wants the room, which grows to its text and
 * is cut only where the panel runs out; `figure`, a readout, right-aligned, never wrapped; `bar`, a figure with a bar
 * of its share after it (`CellBar`); `word`, a short word, a link, or a chip, left-aligned, never wrapped; `age`, when,
 * right-aligned, never wrapped, in the interface's face.
 */
export type ReportColumnKind = 'name' | 'free' | 'figure' | 'bar' | 'word' | 'age'

/** One of a `ReportTable`'s columns. */
export interface ReportColumn<T> {
    /** What it holds, its cells' key. */
    key: string
    /** What it holds, which sets how it sits. */
    kind: ReportColumnKind
    /** Its head; null for a column the one before it explains, such as a chip after a figure. */
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

// The head of a table in a region of someone else's, such as a chart's folded table (`ChartTable`), unpadded.
const BARE_HEAD = 'sticky top-0 bg-surface'

// How a head sits, by its column's kind: over the text it names, so a figure's head is right-aligned.
const HEAD_ALIGN: Record<Exclude<ReportColumnKind, 'bar'>, string> = {
    name: 'text-left',
    free: 'text-left',
    figure: 'text-right',
    word: 'text-left',
    age: 'text-right',
}

// How a cell sits, by its column's kind.
const CELL: Record<Exclude<ReportColumnKind, 'bar'>, string> = {
    name: 'text-left whitespace-nowrap',
    free: 'text-left',
    figure: 'readout text-right whitespace-nowrap',
    word: 'text-left whitespace-nowrap',
    age: 'text-right whitespace-nowrap',
}

/**
 * A report's table (ui/DESIGN.md, "A table of figures"), one row of `rows` each, in `columns`: the first column is the
 * row's head, so it names the row (a `name`, `free`, or `word` column), never a figure or a bar. It is as wide as its
 * content and never wider than its panel, so a row's figures sit by what it names; its `free` column grows to its text
 * and takes the panel's room, cut only past it. It scrolls in its panel under a sticky head, named `label` for a screen
 * reader, in a region of `className` (`max-h-96 px-3 pb-3` unless given); with `scroll` false it is bare, for a region
 * of someone else's (`ChartTable`). `rowKey` keys a row; the table's test id is `testId`, each row's `rowTestId`'s, or
 * what it makes of the row. `top` sets each row's cells at its top, for a row whose free cell stacks rows of its own. A
 * page shows its own `Empty` in its place when it has no rows.
 */
export function ReportTable<T>({
    rows,
    columns,
    rowKey,
    label,
    className = 'max-h-96 px-3 pb-3',
    scroll = true,
    top = false,
    testId,
    rowTestId,
}: {
    rows: readonly T[]
    columns: readonly ReportColumn<T>[]
    rowKey: (row: T) => string
    label: string
    className?: string
    scroll?: boolean
    top?: boolean
    testId?: string
    rowTestId?: string | ((row: T) => string)
}) {
    const table = (
        <Table className="max-w-full" data-testid={testId}>
            <TableHeader className={scroll ? PADDED_HEAD : BARE_HEAD}>
                <TableRow>
                    {columns.map((column, i) => (
                        <ColumnHead key={column.key} column={column} first={i === 0} />
                    ))}
                </TableRow>
            </TableHeader>
            <TableBody>
                {rows.map((row) => (
                    <TableRow
                        key={rowKey(row)}
                        className={cn(top && 'align-top')}
                        data-testid={typeof rowTestId === 'function' ? rowTestId(row) : rowTestId}
                    >
                        {columns.map((column, i) => (
                            <ColumnCell key={column.key} column={column} row={row} first={i === 0} />
                        ))}
                    </TableRow>
                ))}
            </TableBody>
        </Table>
    )
    return scroll ? (
        <PanelScroll label={label} className={className}>
            {table}
        </PanelScroll>
    ) : (
        table
    )
}

function ColumnHead<T>({ column, first }: { column: ReportColumn<T>; first: boolean }) {
    if (column.label === null) {
        return <td aria-hidden />
    }
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
    const held = column.kind === 'free' ? <Free>{content}</Free> : content
    return first ? (
        <th scope="row" className={cn('py-0.5 font-normal', className)}>
            {held}
        </th>
    ) : (
        <TableCell className={className}>{held}</TableCell>
    )
}

/**
 * A free cell's content, as wide as its text, and cut only past the panel's width: a grid whose one item may shrink
 * under its text, which a table's cell alone never lets it. Text is cut to a line; other content cuts its own, as
 * `Clipped` does.
 */
function Free({ children }: { children: ReactNode }) {
    return (
        <div className="grid">
            <div className="min-w-0 truncate">{children}</div>
        </div>
    )
}
