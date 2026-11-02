import type { ReactElement, ReactNode } from 'react'

import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card'

/**
 * A header readout with its page at a glance in a hover card: `children` is the readout, a link or what holds one, and
 * `card` what the card shows, a `ReadoutCard`. Hovered or focused, the card opens; a click still follows the link.
 */
export function ReadoutHover({ card, testId, children }: { card: ReactNode; testId: string; children: ReactElement }) {
    return (
        <HoverCard>
            <HoverCardTrigger asChild>{children}</HoverCardTrigger>
            <HoverCardContent data-testid={testId}>{card}</HoverCardContent>
        </HoverCard>
    )
}

/**
 * A readout's card, as the host's sets the pattern: what it is about and, at the right, a word or two more, then
 * `children`, its rows (`CardRows`) and anything over them, and at its foot a pointer to the page the readout opens,
 * or `foot` for a card whose trigger opens none.
 */
export function ReadoutCard({
    title,
    aside,
    foot = 'Open it for the rest.',
    children,
}: {
    title: ReactNode
    aside?: ReactNode
    foot?: ReactNode
    children: ReactNode
}) {
    return (
        <div className="flex flex-col gap-2.5 text-xs">
            <div className="flex min-w-0 items-baseline justify-between gap-3">
                <span className="truncate font-medium">{title}</span>
                {aside !== undefined && <span className="readout shrink-0 text-muted-foreground">{aside}</span>}
            </div>
            {children}
            <span className="text-muted-foreground">{foot}</span>
        </div>
    )
}

/** A card's rows, each a `CardRow`: labels in a column, their values beside them. */
export function CardRows({ children }: { children: ReactNode }) {
    return <dl className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-x-3 gap-y-1">{children}</dl>
}

/** One row of a card: a label, and its value. */
export function CardRow({ label, children }: { label: string; children: ReactNode }) {
    return (
        <>
            <dt className="panel-label">{label}</dt>
            <dd className="min-w-0 text-muted-foreground">{children}</dd>
        </>
    )
}
