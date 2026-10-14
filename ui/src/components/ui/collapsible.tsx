// shadcn/ui Collapsible, Radix base, ported by hand; see button.tsx. It has no look of its own: the trigger is styled
// by what it wraps (`asChild`), and the content by the caller.
import { Collapsible as CollapsiblePrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'

/**
 * A part of the page that opens and closes. With `asChild` it is its one child, such as a list's row, so the open
 * part needs no wrapper of its own.
 */
function Collapsible(props: ComponentProps<typeof CollapsiblePrimitive.Root>) {
    return <CollapsiblePrimitive.Root data-slot="collapsible" {...props} />
}

/** What opens and closes its `Collapsible`. Radix sets its `aria-expanded`, and its `aria-controls` while open. */
function CollapsibleTrigger(props: ComponentProps<typeof CollapsiblePrimitive.Trigger>) {
    return <CollapsiblePrimitive.Trigger data-slot="collapsible-trigger" {...props} />
}

/** The part that shows only while its `Collapsible` is open. Its children are not rendered while closed. */
function CollapsibleContent(props: ComponentProps<typeof CollapsiblePrimitive.Content>) {
    return <CollapsiblePrimitive.Content data-slot="collapsible-content" {...props} />
}

export { Collapsible, CollapsibleContent, CollapsibleTrigger }
