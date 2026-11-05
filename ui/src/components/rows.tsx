import type { ComponentProps, HTMLAttributes } from 'react'

import { ROW_SUBGRID, rowCells, rowHidden, rowLayout, rowLineFrom } from '@/lib/rows'
import type { RowColumn, RowKind } from '@/lib/rows'
import { cn } from '@/lib/utils'

/**
 * A list of rows of one kind: a grid in its kind's columns, those its width has room for (`rowLayout`), which its rows
 * share as subgrids, so each column is as wide as its widest cell in this list. Anything else in it, a heading or an
 * `Empty`, spans the whole list. `as` is its element, a `ul` unless it is ordered or holds lists (`div`). `sub` makes
 * it a subgrid of the list it is in, so lists stacked in one panel (each pool's slots in the Pools panel) share their
 * columns: that list is a `div` of the same kind, and anything between the two a subgrid of it (`ROW_SUBGRID`).
 */
export function RowList({
    kind,
    as: List = 'ul',
    sub = false,
    className,
    style,
    ...props
}: HTMLAttributes<HTMLElement> & { kind: RowKind; as?: 'ul' | 'ol' | 'div'; sub?: boolean }) {
    if (sub) {
        return <List className={cn(ROW_SUBGRID, '*:col-span-full', className)} style={style} {...props} />
    }
    const layout = rowLayout(kind)
    return (
        <List
            className={cn('grid gap-x-3 *:col-span-full', layout.className, className)}
            style={{ ...layout.style, ...style }}
            {...props}
        />
    )
}

/**
 * A list's row, in a `RowList` of its kind, whose columns it shares as a subgrid. Its children fill the head line one
 * cell per column, in order, so a cell that may be empty still renders, and a column its list leaves out hides the
 * cell in its place; a `RowLine` goes under it. Each cell of the head line is held to its column, its text cut to fit
 * (`rowCells`).
 */
export function ListRow({ kind, className, ...props }: ComponentProps<'li'> & { kind: RowKind }) {
    return (
        <li
            className={cn(ROW_SUBGRID, 'items-center gap-y-1 px-3 py-2.5', rowHidden(kind), rowCells(kind), className)}
            {...props}
        />
    )
}

/**
 * The columns of a kind of row outside a row, so what sits under one (a tool call's body) lines up with it: a subgrid
 * of the `RowList` it is in, as a row is. `alone` makes it a grid of its kind's own columns, for what sits in no list
 * of rows (a transcript's, whose head line is not cells); it lines up only where the columns before its line are fixed.
 */
export function RowGrid({
    kind,
    alone = false,
    className,
    style,
    ...props
}: ComponentProps<'div'> & { kind: RowKind; alone?: boolean }) {
    if (alone) {
        const layout = rowLayout(kind, 0)
        return (
            <div
                className={cn('grid gap-x-3 px-3', layout.className, rowHidden(kind), className)}
                style={{ ...layout.style, ...style }}
                {...props}
            />
        )
    }
    return <div className={cn(ROW_SUBGRID, 'px-3', rowHidden(kind), className)} style={style} {...props} />
}

/** A line under a row's head line, from the named column to the row's end: a summary, its links, an earlier run. */
export function RowLine({ from, className, ...props }: ComponentProps<'div'> & { from: RowColumn }) {
    return <div className={cn(rowLineFrom(from), 'min-w-0', className)} {...props} />
}
