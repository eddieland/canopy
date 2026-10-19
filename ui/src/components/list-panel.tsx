import type { ComponentProps, ReactNode } from 'react'

import { OrderToggle } from '@/components/order-toggle'
import { Panel, PanelHeader } from '@/components/panel'
import type { ListName } from '@/lib/list-order'

/**
 * A detail page's supporting list (runs, reviews, decisions) in its panel: headed by its noun and how many it holds,
 * with its order's toggle once it holds two to order. With none, the panel is its header alone, `0` at its right, and
 * no row saying so: the count already says it, and an empty list takes no more of the page than its name. A list the
 * page's subject can never have (a ticketless PR's runs) is left out instead, by its page.
 */
export function ListPanel({
    label,
    count,
    list,
    children,
    ...props
}: Omit<ComponentProps<'section'>, 'children'> & {
    /** The list's noun, its panel's name: `Runs`, `Decisions`. */
    label: string
    /** How many it holds; with none, `children` are left out. */
    count: number
    /** The list's name for its order (`OrderToggle`), when it can be flipped. */
    list?: ListName
    /** The list itself, shown while it holds any. */
    children: ReactNode
}) {
    return (
        <Panel {...props}>
            <PanelHeader label={label}>
                <span className="flex items-center gap-2">
                    {list !== undefined && count > 1 && <OrderToggle list={list} />}
                    <span className="readout text-xs text-muted-foreground">{count}</span>
                </span>
            </PanelHeader>
            {count > 0 && children}
        </Panel>
    )
}
