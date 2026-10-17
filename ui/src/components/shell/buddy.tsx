import { useRouterState } from '@tanstack/react-router'
import { X } from 'lucide-react'
import { useEffect, useEffectEvent, useRef, useState } from 'react'
import type { CSSProperties } from 'react'

import { HatDrawing } from '@/components/hat'
import { useFits } from '@/hooks/use-fits'
import { setBuddy, tipFor } from '@/lib/buddy'
import type { View } from '@/lib/buddy'
import { useWardrobe } from '@/lib/hats'
import type { HatId } from '@/lib/hats'
import { cn } from '@/lib/utils'
import type { FileRoutesById } from '@/routeTree.gen'

/** How long a tip stays up before Sprig takes the hint. */
const TIP_SECONDS = 20
/** The shortest and longest Sprig waits, after a tip closes, before offering the next unasked: picked at random. */
const WAIT_SECONDS = { least: 120, most: 360 }
/** How far Sprig may stand over the foot of the rail's blocks, the spend, in a rail too short to hold it whole. */
const OVERLAP_PX = 40

/** How Sprig fits its slot: with the room for its bubble too, or only for itself, standing over the spend a little. */
type Room = 'roomy' | 'tight'

/** The tip Sprig last offered: on which view, its place in that view's tips, whether it is up, and if it was asked. */
interface Offer {
    /** The view it was offered on, which it is about. */
    view: View | undefined
    /** How many tips came before it, since the page loaded: its place in its view's tips (`tipFor`). */
    n: number
    /** Whether its bubble is up, till it is closed or its time runs out. */
    open: boolean
    /** Whether the reader asked for it with a click, rather than Sprig offering it on its own. */
    asked: boolean
}

/**
 * Sprig, the helper at the foot of the side rail: a bent wire with a sprig on top and googly eyes that follow the
 * pointer. Now and then, at random, it offers a tip about the view on screen, the dumber the better (`TIPS` in
 * src/lib/buddy.ts); clicking it offers another at once. Its clock is its own: turning a page neither offers a tip nor
 * puts the next one off, and a tip offered on one view is not shown on another. The tip closes with its button, or by
 * itself after a while, and the next comes a few minutes after that. Settings turns Sprig off, and so does the tip's
 * "Don't show me tips again".
 *
 * It has a slot of its own in the rail's column, between what the rail holds and its footer: the slot is the room
 * left under the rail's blocks, and Sprig stands at its foot. A slot with room for Sprig and its bubble covers
 * nothing. A shorter one, as a laptop's window leaves, still shows Sprig if it can stand over the foot of the spend
 * by `OVERLAP_PX` or less, as the operator asked; there the bubble would cover the blocks above, so a tip shows only
 * when asked for, with a click, and Sprig lets the ones it would offer on its own pass. A slot shorter still leaves
 * Sprig out, rather than squeeze the blocks above.
 */
export function Buddy() {
    const view = viewOf(useRouterState({ select: (state) => state.matches.at(-1)?.routeId }))
    // Read once per page load, as the ticker's reel is: the tip must not change under the reader.
    const [today] = useState(() => Date.now())
    // Closed until the first is offered, the bubble holding the view's first tip's room meanwhile.
    const [offer, setOffer] = useState<Offer>({ view, n: 0, open: false, asked: false })
    const tip = tipFor(offer.view, offer.n, today)
    const [slot, room] = useFits(roomFor)
    const { worn } = useWardrobe()
    const another = () => setOffer({ view, n: offer.n + 1, open: true, asked: true })
    // Offers the next tip unasked, for the view on screen when the time comes, if the bubble would cover nothing and
    // the tab is in sight to read it.
    const offerUnasked = useEffectEvent(() => {
        if (room === 'roomy' && document.visibilityState === 'visible') {
            setOffer({ view, n: offer.n + 1, open: true, asked: false })
        }
    })
    const close = () => setOffer((last) => ({ ...last, open: false }))
    // Waits while no tip is up, a while picked at random, then offers one. One let pass waits again.
    useEffect(() => {
        if (offer.open) {
            return
        }
        let timer: ReturnType<typeof globalThis.setTimeout> | undefined
        const wait = () => {
            const seconds = WAIT_SECONDS.least + Math.random() * (WAIT_SECONDS.most - WAIT_SECONDS.least)
            timer = globalThis.setTimeout(() => {
                offerUnasked()
                wait()
            }, seconds * 1000)
        }
        wait()
        return () => globalThis.clearTimeout(timer)
    }, [offer.open])
    const shown = offer.open && offer.view === view && (room === 'roomy' || offer.asked)
    // A new tip opens a new bubble: the key remounts it, popping it in, and raises Sprig's brows. Closed, the bubble
    // keeps the last tip's room, whatever the page, so Sprig does not move. Sprig, and a bubble shown in a tight slot,
    // rise out of the slot over the blocks above: positioned, so they paint over them.
    return (
        <div ref={slot} className="flex min-h-0 flex-1 flex-col justify-end print:hidden">
            <aside
                aria-label="Sprig"
                data-testid="buddy"
                data-room={room === false ? undefined : room}
                className={cn(
                    'relative flex shrink-0 flex-col items-start gap-2 px-3 pt-3 pb-1',
                    room === false && 'invisible',
                )}
            >
                <Bubble key={offer.n} tip={tip} open={offer.open} shown={shown} onAnother={another} onClose={close} />
                <button
                    type="button"
                    aria-label="Ask Sprig for a tip"
                    data-testid="buddy-sprig"
                    onClick={another}
                    className={cn(
                        'rounded-md p-1 transition-transform',
                        'outline-none focus-visible:ring-2 focus-visible:ring-ring motion-safe:hover:-translate-y-0.5',
                    )}
                >
                    <Figure cue={offer.n} hat={worn} />
                </button>
            </aside>
        </div>
    )
}

/**
 * The view a route is: every route but those that only redirect, the root and the guide's. Returning the route as a
 * view is what holds `TIPS` to the routes, so a new route fails the type check until it has tips of its own.
 */
function viewOf(routeId: keyof FileRoutesById | undefined): View | undefined {
    return routeId === undefined || routeId === '__root__' || routeId === '/' || routeId === '/guide/'
        ? undefined
        : routeId
}

/**
 * How Sprig, the slot's one child, fits: whole, its bubble included, or the figure alone once it may stand over the
 * blocks above by `OVERLAP_PX`. False for neither.
 */
function roomFor(slot: HTMLElement): Room | false {
    const sprig = slot.firstElementChild
    const figure = sprig?.lastElementChild
    if (!(sprig instanceof HTMLElement) || !(figure instanceof HTMLElement)) {
        return false
    }
    if (sprig.offsetHeight <= slot.clientHeight) {
        return 'roomy'
    }
    // From the figure's top to Sprig's foot: the aside is positioned, so it is the figure's offsetParent.
    return sprig.offsetHeight - figure.offsetTop <= slot.clientHeight + OVERLAP_PX ? 'tight' : false
}

/**
 * The speech bubble above Sprig: the tip, another, and the way out. Its tail points down at Sprig. It closes itself
 * once its tip has been up a while, counted from when it opened, shown or not: a tip is only offered where it shows.
 * Not `shown`, it is hidden but keeps its room, so Sprig does not move.
 */
function Bubble({
    tip,
    open,
    shown,
    onAnother,
    onClose,
}: {
    tip: string
    open: boolean
    shown: boolean
    onAnother: () => void
    onClose: () => void
}) {
    const expire = useEffectEvent(onClose)
    useEffect(() => {
        if (!open) {
            return
        }
        const timer = globalThis.setTimeout(expire, TIP_SECONDS * 1000)
        return () => globalThis.clearTimeout(timer)
    }, [open])
    return (
        <div
            data-testid="buddy-tip"
            className={cn(
                'animate-buddy-tip relative w-full rounded-md border bg-surface-raised p-3 text-sm',
                !shown && 'invisible',
            )}
        >
            <p className="panel-label mb-1">Sprig</p>
            <p>{tip}</p>
            <div className="mt-2.5 flex flex-col items-start gap-1 text-xs">
                <button
                    type="button"
                    onClick={onAnother}
                    className="text-accent underline-offset-4 hover:underline"
                    data-testid="buddy-another"
                >
                    Another tip
                </button>
                <button
                    type="button"
                    onClick={() => setBuddy('off')}
                    title="Turns Sprig off. Settings turns it back on."
                    className="text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
                    data-testid="buddy-dismiss"
                >
                    Don&apos;t show me tips again
                </button>
            </div>
            <button
                type="button"
                aria-label="Close the tip"
                onClick={onClose}
                className="absolute top-2 right-2 rounded-sm p-0.5 text-muted-foreground hover:text-foreground"
                data-testid="buddy-close"
            >
                <X className="size-4" />
            </button>
            {/* The tail: a square turned on its corner, its two outer edges bordered, tucked under the bubble's. */}
            <span
                aria-hidden
                className="absolute -bottom-[5px] left-6 size-2.5 rotate-45 border-r border-b bg-surface-raised"
            />
        </div>
    )
}

/**
 * Sprig itself: a paperclip's bent wire, a sprig of leaf on top, the hat it wears (bought in Settings), googly eyes
 * under brows that rise with each new tip, and a keyboard in front of its foot, to help vibe code on. The eyes blink
 * now and then and look toward the pointer, and the keys are typed on in bursts, but under reduced motion, which keeps
 * them still.
 */
function Figure({ cue, hat }: { cue: number; hat: HatId | null }) {
    const figure = useRef<SVGSVGElement>(null)
    useEffect(() => {
        const svg = figure.current
        if (svg === null || globalThis.matchMedia('(prefers-reduced-motion: reduce)').matches) {
            return
        }
        const look = (event: PointerEvent) => {
            for (const eye of svg.querySelectorAll<SVGGElement>('[data-eye]')) {
                const box = eye.getBoundingClientRect()
                const dx = event.clientX - (box.left + box.width / 2)
                const dy = event.clientY - (box.top + box.height / 2)
                const distance = Math.max(Math.hypot(dx, dy), 1)
                // At most 2.5 units off center, in the drawing's own units, and less for a pointer close by.
                const reach = 2.5 * Math.min(1, distance / 120)
                const x = ((dx / distance) * reach).toFixed(2)
                const y = ((dy / distance) * reach).toFixed(2)
                eye.querySelector('[data-pupil]')?.setAttribute('transform', `translate(${x} ${y})`)
            }
        }
        globalThis.addEventListener('pointermove', look, { passive: true })
        return () => globalThis.removeEventListener('pointermove', look)
    }, [])
    return (
        <svg ref={figure} viewBox="0 -6 48 92" className="h-24 w-[3.25rem] overflow-visible" aria-hidden>
            <path
                d="M24 12 C24 8 25 5 28 3"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                className="text-buddy-leaf"
            />
            <path
                d="M28 3 C30 -3 38 -4 43 -1 C40 4 33 7 28 3 Z"
                fill="currentColor"
                fillOpacity="0.85"
                className="text-buddy-leaf"
            />
            <path
                d="M18 66 V32 a6 6 0 0 1 12 0 V72 a10 10 0 0 1 -20 0 V26 a14 14 0 0 1 28 0 V62"
                fill="none"
                stroke="currentColor"
                strokeWidth="3"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="text-muted-foreground"
            />
            <Keyboard />
            {hat === null ? null : <HatDrawing id={hat} />}
            <g key={cue} className="animate-buddy-brows text-foreground">
                <path
                    d="M10 25 Q15 21 20 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                />
                <path
                    d="M28 24 Q33 21 38 25"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                />
            </g>
            <g className="animate-buddy-blink">
                {[15, 33].map((cx) => (
                    <g key={cx} data-eye>
                        <circle cx={cx} cy="33" r="6.5" className="fill-buddy-eye stroke-buddy-pupil" />
                        <circle data-pupil cx={cx} cy="34" r="2.8" className="fill-buddy-pupil" />
                    </g>
                ))}
            </g>
        </svg>
    )
}

/** The keyboard's top face, a trapezoid seen from above and in front: its back edge, then its front edge. */
const DECK = { back: { y: 74, left: 7, right: 41 }, front: { y: 83, left: 2, right: 46 } }
/** How far the case stands below the front edge of its top face. */
const LIP = 2.5
/** A key's height, and the gap between two keys. */
const KEY = { height: 2, gap: 0.5 }
/** Each row of keys, back to front: where its top is, and the width of each key, as shares of the row. */
const ROWS: readonly { y: number; keys: readonly number[] }[] = [
    { y: 75.3, keys: Array.from({ length: 9 }, () => 1) },
    { y: 77.9, keys: Array.from({ length: 9 }, () => 1) },
    { y: 80.5, keys: [1, 1, 4.5, 1, 1] },
]
/** The case's outline: the top face, and the lip under its front edge. */
const CASE = [
    `M${DECK.back.left} ${DECK.back.y} H${DECK.back.right}`,
    `L${DECK.front.right} ${DECK.front.y} V${DECK.front.y + LIP}`,
    `H${DECK.front.left} V${DECK.front.y} Z`,
].join(' ')
/** The keys Sprig presses in each burst, in the order it presses them: a row, then a key in it. The space bar last. */
const TYPED: readonly (readonly [number, number])[] = [
    [0, 2],
    [1, 6],
    [0, 4],
    [1, 1],
    [0, 7],
    [2, 2],
]

/**
 * The keyboard Sprig vibe codes on, in front of the foot of its wire: a case seen from above, three rows of keys, the
 * last a space bar. A few keys light in the accent as Sprig types on them, a burst every few seconds.
 */
function Keyboard() {
    return (
        <g data-keyboard>
            <path
                d={CASE}
                strokeWidth="1"
                strokeLinejoin="round"
                className="fill-buddy-keyboard stroke-buddy-keyboard"
            />
            {ROWS.map((row, r) =>
                keysOf(row).map((key, k) => {
                    const typed = TYPED.findIndex(([tr, tk]) => tr === r && tk === k)
                    return (
                        <rect
                            key={`${r}-${k}`}
                            x={key.x}
                            y={row.y}
                            width={key.width}
                            height={KEY.height}
                            rx="0.4"
                            className={cn('fill-buddy-key', typed >= 0 && 'animate-buddy-key')}
                            style={typed >= 0 ? ({ '--key': typed } as CSSProperties) : undefined}
                        />
                    )
                }),
            )}
        </g>
    )
}

/** Where each key of a row sits across it: the row spans the top face at its height, less a margin each side. */
function keysOf(row: { y: number; keys: readonly number[] }): { x: number; width: number }[] {
    const { back, front } = DECK
    const share = (row.y + KEY.height / 2 - back.y) / (front.y - back.y)
    const left = back.left + (front.left - back.left) * share + 1.2
    const right = back.right + (front.right - back.right) * share - 1.2
    const unit = (right - left - KEY.gap * (row.keys.length - 1)) / row.keys.reduce((sum, keys) => sum + keys, 0)
    let x = left
    return row.keys.map((keys) => {
        const key = { x, width: unit * keys }
        x += key.width + KEY.gap
        return key
    })
}
