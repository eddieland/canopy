import { useState } from 'react'
import type { ComponentProps, ReactNode } from 'react'

import { Disclosure } from '@/components/disclosure'
import { Panel, PanelHeader } from '@/components/panel'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'

/**
 * A panel that arrives folded to its header, for what a page keeps at hand but seldom reads whole (a run's memory):
 * its label, a `readout` that says what it holds in a few words, and a `Disclosure`, `Show <what>`, that opens its
 * rows under the header. Its rows are built only once opened, and close again with the page.
 */
export function FoldPanel({
    label,
    readout,
    what,
    children,
    ...props
}: Omit<ComponentProps<'section'>, 'children'> & {
    /** The panel's name, as its header says it. */
    label: string
    /** What it holds, in a few words, at the header's right: what the operator reads to decide whether to open it. */
    readout: ReactNode
    /** What the `Disclosure` opens, in its words: `memory` reads `Show memory`. */
    what: string
    /** The rows it opens to. */
    children: ReactNode
}) {
    const [open, setOpen] = useState(false)
    return (
        <Collapsible asChild open={open} onOpenChange={setOpen}>
            <Panel {...props}>
                <PanelHeader label={label}>
                    <span className="flex items-center gap-3">
                        {readout}
                        <Disclosure open={open} what={what} />
                    </span>
                </PanelHeader>
                <CollapsibleContent>{children}</CollapsibleContent>
            </Panel>
        </Collapsible>
    )
}
