import { useState } from 'react'
import type { ReactNode } from 'react'

import { Disclosure } from '@/components/disclosure'
import { PanelScroll } from '@/components/panel'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'

/**
 * The table of a chart's numbers, under the chart (ui/DESIGN.md, Charts), folded until opened: a `Disclosure` that
 * says how many rows it holds, `Show 7 days as a table`, and the table under it in a `PanelScroll` named `label`, of
 * `className`'s height. Folded, the table stays in the page for a screen reader, which cannot see the chart, but out
 * of sight and out of the keyboard's way, with no scrolling region to stop on. `what` is its rows in words,
 * `7 days`; `testId` the scroll's test id.
 */
export function ChartTable({
    what,
    label,
    className,
    testId,
    children,
}: {
    what: string
    label: string
    className?: string
    testId?: string
    children: ReactNode
}) {
    const [open, setOpen] = useState(false)
    return (
        <Collapsible open={open} onOpenChange={setOpen} className="flex flex-col gap-2">
            <Disclosure open={open} what={`${what} as a table`} className="-ml-2 self-start" />
            <CollapsibleContent>
                <PanelScroll label={label} className={className} data-testid={testId}>
                    {children}
                </PanelScroll>
            </CollapsibleContent>
            {/* Radix leaves a closed part out of the page, so the folded table is a copy for a screen reader alone. */}
            {!open && <div className="sr-only">{children}</div>}
        </Collapsible>
    )
}
