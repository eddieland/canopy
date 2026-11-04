import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/**
 * A figure in a table with a bar of its share of the column's largest after it (ui/DESIGN.md, "A bar in a cell"):
 * spent by ticket, by model, by landed ticket. It is two cells, the figure's and the bar's, so the table sizes the
 * figure's column to its widest figure and every bar starts at one edge, whatever the figures hold; a fixed width
 * guessed for them wraps the first figure longer than the guess. Its head is a `CellBarHead`.
 *
 * `percent` is the share, 0 to 100 (`barPercent`); `fill` the bar's, `muted-foreground` unless the figure is a
 * series' with a fill of its own. `className` is the figure's cell's, `barClassName` the bar's cell's. The bar is the
 * eye's: a screen reader reads the figure.
 */
export function CellBar({
    percent,
    fill = 'bg-muted-foreground',
    className,
    barClassName,
    children,
}: {
    percent: number
    fill?: string
    className?: string
    barClassName?: string
    children: ReactNode
}) {
    return (
        <>
            <td className={cn('pl-3 text-right whitespace-nowrap', className)}>{children}</td>
            {/* The bar is the eye's: a screen reader reads its figure, the cell before it. */}
            {/* oxlint-disable-next-line jsx-a11y/control-has-associated-label */}
            <td aria-hidden className={cn('pl-2', barClassName)}>
                <span className="block h-1.5 min-w-16 rounded-full bg-surface-raised" data-testid="cell-bar">
                    <span
                        className={cn('block h-full rounded-full', fill)}
                        style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
                    />
                </span>
            </td>
        </>
    )
}

/**
 * The head of a `CellBar`'s column: its name over the figure's cell, right-aligned as every figure's head is, and an
 * empty cell over the bar's, so the head row has as many cells as a row does. `className` is the name's cell's.
 */
export function CellBarHead({ className, children }: { className?: string; children: ReactNode }) {
    return (
        <>
            <th className={cn('panel-label pb-1.5 pl-3 text-right font-normal whitespace-nowrap', className)}>
                {children}
            </th>
            <td aria-hidden />
        </>
    )
}
