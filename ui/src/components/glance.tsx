import { createContext, use } from 'react'
import type { ReactElement, ReactNode } from 'react'

import type { RunState } from '@/api/types'
import { RunDot } from '@/components/status'
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card'
import { cn } from '@/lib/utils'

// Whether what renders is inside an open card already: a link there opens no card of its own, so one card never
// stacks on another.
const InGlance = createContext(false)

/**
 * A link with its page at a glance in a hover card (ui/DESIGN.md, "A link's page at a glance is a hover card"):
 * `children` is the link, or what holds it, and `card` what the card shows, a `GlanceCard`, made only once the card
 * opens, so a card that reads its data reads nothing until then. Hovered or focused, the card opens; a click still
 * follows the link. Inside another card it is its link alone.
 */
export function Glance({
    card,
    testId,
    align,
    children,
}: {
    card: ReactNode
    testId?: string
    align?: 'start' | 'center' | 'end'
    children: ReactElement
}) {
    const nested = use(InGlance)
    if (nested) {
        return children
    }
    return (
        <HoverCard>
            <HoverCardTrigger asChild>{children}</HoverCardTrigger>
            <HoverCardContent data-testid={testId} align={align}>
                <InGlance value>{card}</InGlance>
            </HoverCardContent>
        </HoverCard>
    )
}

/**
 * A hover card's content, as the host's sets the pattern: what it is about, after its state's dot when it has a
 * state, in monospace when it is a reference (`mono`, and whenever it has a state), and, at the right, a word or two
 * more; under them `name`, what the journal calls it, when it has a name beside its reference; then `children`, its
 * rows (`CardRows`) and anything over them, and at its foot a pointer to the page its link opens, or `foot` for a card
 * whose trigger opens none, null for no foot: a reference's card, whose link names its page already.
 */
export function GlanceCard({
    title,
    mono = false,
    state,
    aside,
    name,
    foot = 'Open it for the rest.',
    children,
}: {
    title: ReactNode
    mono?: boolean
    state?: RunState
    aside?: ReactNode
    name?: ReactNode
    foot?: ReactNode
    children?: ReactNode
}) {
    return (
        <div className="flex flex-col gap-2.5 text-xs">
            <div className="flex flex-col gap-1">
                <div className="flex min-w-0 items-baseline justify-between gap-3">
                    <span className="flex min-w-0 items-baseline gap-1.5 font-medium">
                        {state !== undefined && <RunDot state={state} />}
                        <span className={cn('min-w-0 wrap-anywhere', (mono || state !== undefined) && 'readout')}>
                            {title}
                        </span>
                    </span>
                    {aside !== undefined && <span className="shrink-0 readout text-muted-foreground">{aside}</span>}
                </div>
                {name !== undefined && name !== null && (
                    <p className="line-clamp-2 text-sm font-medium wrap-break-word">{name}</p>
                )}
            </div>
            {children}
            {foot !== null && <span className="text-muted-foreground">{foot}</span>}
        </div>
    )
}

/** What a card's subject said, or what is said of it, cut to a few lines: untrusted text, kept text. */
export function CardWords({ children }: { children: ReactNode }) {
    return <p className="line-clamp-3 wrap-break-word whitespace-pre-line text-muted-foreground">{children}</p>
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
            <dd className="min-w-0 wrap-break-word text-muted-foreground">{children}</dd>
        </>
    )
}
