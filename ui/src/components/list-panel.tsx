import type { ComponentProps, ReactNode } from 'react'

import { OrderToggle } from '@/components/order-toggle'
import { Panel, PanelHeader } from '@/components/panel'
import type { ListName } from '@/lib/list-order'

/**
 * A detail page's supporting list (its runs, reviews, or decisions) in a panel of its own: headed by its name and how
 * many it holds, with its order's toggle once it holds two to order, and the list under it. An empty list collapses to
 * its header, `0` and nothing under it, with why it is empty on the count's hover, so a list that has not filled takes
 * a line of the page rather than a panel (ui/DESIGN.md, the detail skeleton). A list that can never fill on its page,
 * such as a ticketless PR's runs, is left out rather than shown empty.
 */
export function ListPanel({
    label,
    count,
    list,
    empty,
    children,
    ...props
}: Omit<ComponentProps<'section'>, 'children'> & {
    /** The list's name in its header, its noun: `Runs`, `Reviews`, `Decisions`. */
    label: string
    /** How many it holds, which its header counts. */
    count: number
    /** Which list's order it keeps (src/lib/list-order.ts). */
    list: ListName
    /** Why it is empty, in the words an `Empty` would say, on the count's hover while it is. */
    empty: string
    /** The list itself, shown only while it holds something. */
    children: ReactNode
}) {
    return (
        <Panel {...props}>
            <PanelHeader label={label}>
                <span className="flex items-center gap-2">
                    {count > 1 && <OrderToggle list={list} />}
                    <span
                        className="readout text-xs text-muted-foreground"
                        title={count === 0 ? empty : undefined}
                        data-testid="list-count"
                    >
                        {count}
                    </span>
                </span>
            </PanelHeader>
            {count > 0 && children}
        </Panel>
    )
}
