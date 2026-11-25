import { createContext, use, useEffect, useRef, useState } from 'react'
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
 * opens, so a card that reads its data reads nothing until then. Hovered or focused, the card opens, and stays open
 * while the pointer is on the link or on the card, so it can be read at leisure; a click still follows the link, and so
 * does a click on a link the card covers, since the pointer passes through it. It opens under the link, or on `side`,
 * as a reference's opens beside it, clear of the rows below. Inside another card it is its link alone.
 */
export function Glance({
    card,
    testId,
    align,
    side,
    children,
}: {
    card: ReactNode
    testId?: string
    align?: 'start' | 'center' | 'end'
    side?: 'top' | 'right' | 'bottom' | 'left'
    children: ReactElement
}) {
    const nested = use(InGlance)
    const [open, setOpen] = useState(false)
    const link = useRef<HTMLAnchorElement | null>(null)
    const content = useRef<HTMLDivElement | null>(null)
    // Where the pointer last was, and whether the card stays open for it: it does while the pointer is over the card.
    const pointer = useRef<{ x: number; y: number } | null>(null)
    const held = useRef(false)
    useEffect(() => {
        if (!open) {
            return
        }
        const moved = (event: PointerEvent) => {
            pointer.current = { x: event.clientX, y: event.clientY }
            // Held, it closes once the pointer is on neither the card nor its link.
            if (held.current && !over(content.current, pointer.current) && !over(link.current, pointer.current)) {
                held.current = false
                setOpen(false)
            }
        }
        // Escape closes it wherever the pointer is.
        const pressed = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                held.current = false
                setOpen(false)
            }
        }
        document.addEventListener('pointermove', moved)
        document.addEventListener('keydown', pressed)
        return () => {
            document.removeEventListener('pointermove', moved)
            document.removeEventListener('keydown', pressed)
        }
    }, [open])
    if (nested) {
        return children
    }
    return (
        <HoverCard
            open={open}
            onOpenChange={(next) => {
                // The pointer left the link for the card: the card stays, to be read, until the pointer leaves it too.
                if (!next && over(content.current, pointer.current)) {
                    held.current = true
                    return
                }
                held.current = false
                setOpen(next)
            }}
        >
            <HoverCardTrigger asChild ref={link}>
                {children}
            </HoverCardTrigger>
            {/* It holds nothing to point at, so the pointer passes through it: a link it covers still takes its
                click. It is held open by where the pointer is, not by the pointer's events on it. */}
            <HoverCardContent
                ref={content}
                data-testid={testId}
                align={align}
                side={side}
                className="pointer-events-none"
            >
                <InGlance value>{card}</InGlance>
            </HoverCardContent>
        </HoverCard>
    )
}

// How far past a card's edge still counts as on it: the gap between it and its link, so crossing the gap holds it.
const REACH_PX = 8

// Whether `point` is on `element`, or within the gap around it.
function over(element: HTMLElement | null, point: { x: number; y: number } | null): boolean {
    if (element === null || point === null) {
        return false
    }
    const box = element.getBoundingClientRect()
    return (
        point.x >= box.left - REACH_PX &&
        point.x <= box.right + REACH_PX &&
        point.y >= box.top - REACH_PX &&
        point.y <= box.bottom + REACH_PX
    )
}

/**
 * A hover card's content, as the host's sets the pattern: what it is about, after its state's dot when it has a
 * state, in monospace when it is a reference (`mono`, and whenever it has a state), and, at the right, a word or two
 * more; under them `name`, what the journal calls it, when it has a name beside its reference, and `chips`, a line of
 * what kind of thing it is; then `children`, its
 * rows (`CardRows`) and anything over them, and at its foot a pointer to the page its link opens, or `foot` for a card
 * whose trigger opens none, null for no foot: a reference's card, whose link names its page already.
 */
export function GlanceCard({
    title,
    mono = false,
    state,
    aside,
    name,
    chips,
    foot = 'Open it for the rest.',
    children,
}: {
    title: ReactNode
    mono?: boolean
    state?: RunState
    aside?: ReactNode
    name?: ReactNode
    chips?: ReactNode
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
                {chips !== undefined && <div className="mt-0.5 flex flex-wrap items-center gap-1">{chips}</div>}
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

/** A card's rows, each a `CardRow`: labels in a column, their values beside them, under a hairline that sets the
 * facts apart from what the card is about. */
export function CardRows({ children }: { children: ReactNode }) {
    return <dl className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-x-3 gap-y-1 border-t pt-2.5">{children}</dl>
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
