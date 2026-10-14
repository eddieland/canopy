import type { ComponentProps } from 'react'

import { rowLayout, rowLineFrom } from '@/lib/rows'
import type { RowColumn, RowKind } from '@/lib/rows'
import { cn } from '@/lib/utils'

/**
 * A list's row: a grid in its kind's columns, those the width of its list has room for (`rowLayout`). Its children
 * fill the head line one cell per column, in order, so a cell that may be empty still renders, and a column left out
 * hides the cell in its place; a `RowLine` goes under it.
 */
export function ListRow({ kind, className, style, ...props }: ComponentProps<'li'> & { kind: RowKind }) {
    const layout = rowLayout(kind)
    return (
        <li
            className={cn('grid items-center gap-x-3 gap-y-1 px-3 py-2.5', layout.className, className)}
            style={{ ...layout.style, ...style }}
            {...props}
        />
    )
}

/** The columns of a kind of row outside a row, so what sits under one (a tool call's body) lines up with it. */
export function RowGrid({ kind, className, style, ...props }: ComponentProps<'div'> & { kind: RowKind }) {
    const layout = rowLayout(kind)
    return (
        <div
            className={cn('grid gap-x-3 px-3', layout.className, className)}
            style={{ ...layout.style, ...style }}
            {...props}
        />
    )
}

/** A line under a row's head line, from the named column to the row's end: a summary, its links, an earlier run. */
export function RowLine({ from, className, ...props }: ComponentProps<'div'> & { from: RowColumn }) {
    return <div className={cn(rowLineFrom(from), 'min-w-0', className)} {...props} />
}
