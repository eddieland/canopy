import { ChevronRight } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { CollapsibleTrigger } from '@/components/ui/collapsible'

/**
 * What opens a part of the page under it and closes it again (ui/DESIGN.md, "Modes and disclosures"): a ghost `xs`
 * button, a chevron that turns down while open, and what it does in words, `Show <what>` closed and `Hide <what>`
 * open. It is its `Collapsible`'s trigger, so it sits inside one, and Radix keeps its `aria-expanded` in step. `open`
 * is that `Collapsible`'s state, which its words follow. Where several sit on a page, `of` names whose part it
 * opens to a screen reader, after the words it shows: `Hide diff of src/app.ts`.
 */
export function Disclosure({
    open,
    what,
    of = '',
    className,
    ...props
}: {
    open: boolean
    what: string
    of?: string
    className?: string
    'data-testid'?: string
}) {
    const words = `${open ? 'Hide' : 'Show'} ${what}`
    return (
        <CollapsibleTrigger asChild>
            <Button
                variant="ghost"
                size="xs"
                className={className}
                aria-label={of === '' ? undefined : `${words} of ${of}`}
                {...props}
            >
                <ChevronRight
                    aria-hidden
                    className="group-data-[state=open]/button:rotate-90 motion-safe:transition-transform"
                />
                {words}
            </Button>
        </CollapsibleTrigger>
    )
}
