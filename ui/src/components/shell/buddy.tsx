import { useRouterState } from '@tanstack/react-router'
import { X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { HatDrawing } from '@/components/hat'
import { useFits } from '@/hooks/use-fits'
import { pageOf, setBuddy, tipFor } from '@/lib/buddy'
import type { Page } from '@/lib/buddy'
import { useWardrobe } from '@/lib/hats'
import type { HatId } from '@/lib/hats'
import { cn } from '@/lib/utils'

/** How long a tip stays up before Sprig takes the hint. */
const TIP_SECONDS = 20
/** How far Sprig may stand over the foot of the rail's blocks, the spend, in a rail too short to hold it whole. */
const OVERLAP_PX = 40

/** How Sprig fits its slot: with the room for its bubble too, or only for itself, standing over the spend a little. */
type Room = 'roomy' | 'tight'

/**
 * Sprig, the helper at the foot of the side rail: a bent wire with a sprig on top and googly eyes that follow the
 * pointer. On every page it offers a tip about that page, the dumber the better (`TIPS` in src/lib/buddy.ts); clicking
 * it offers another. The tip closes with its button, or by itself after a while. Settings turns Sprig off, and so
 * does the tip's "Don't show me tips again".
 *
 * It has a slot of its own in the rail's column, between what the rail holds and its footer: the slot is the room
 * left under the rail's blocks, and Sprig stands at its foot. A slot with room for Sprig and its bubble covers
 * nothing. A shorter one, as a laptop's window leaves, still shows Sprig if it can stand over the foot of the spend
 * by `OVERLAP_PX` or less, as the operator asked; there the bubble would cover the blocks above, so a tip shows only
 * when asked for, with a click. A slot shorter still leaves Sprig out, rather than squeeze the blocks above.
 */
export function Buddy() {
    const pathname = useRouterState({ select: (state) => state.location.pathname })
    const page = pageOf(pathname)
    // Read once per page load, as the ticker's reel is: the tip must not change under the reader.
    const [today] = useState(() => Date.now())
    // How many more tips the reader asked for, counted per page: a new one starts at its own first tip.
    const [asked, setAsked] = useState<{ page: Page | undefined; n: number }>({ page, n: 0 })
    const n = asked.page === page ? asked.n : 0
    const another = () => setAsked({ page, n: n + 1 })
    const tip = tipFor(pathname, n, today)
    const [slot, room] = useFits(roomFor)
    const { worn } = useWardrobe()
    // A different tip opens a new bubble: the key remounts it, open, and raises Sprig's brows. A page that offers the
    // tip already shown (another of the section's pages) leaves the bubble as it is, open or closed. Sprig, and a
    // bubble shown in a tight slot, rise out of the slot over the blocks above: positioned, so they paint over them.
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
                <Bubble key={tip} tip={tip} shown={room === 'roomy' || n > 0} onAnother={another} />
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
                    <Figure cue={tip} hat={worn} />
                </button>
            </aside>
        </div>
    )
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
 * The speech bubble above Sprig: the tip, another, and the way out. Its tail points down at Sprig. Closed, or not
 * `shown`, it is hidden but keeps its room, so Sprig does not move.
 */
function Bubble({ tip, shown, onAnother }: { tip: string; shown: boolean; onAnother: () => void }) {
    const [open, setOpen] = useState(true)
    useEffect(() => {
        const timer = globalThis.setTimeout(() => setOpen(false), TIP_SECONDS * 1000)
        return () => globalThis.clearTimeout(timer)
    }, [])
    return (
        <div
            data-testid="buddy-tip"
            className={cn(
                'animate-buddy-tip relative w-full rounded-md border bg-surface-raised p-3 text-sm',
                !(open && shown) && 'invisible',
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
                onClick={() => setOpen(false)}
                className="absolute top-2 right-2 rounded-sm p-0.5 text-muted-foreground hover:text-foreground"
                data-testid="buddy-close"
            >
                <X className="size-3.5" />
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
 * Sprig itself: a paperclip's bent wire, a sprig of leaf on top, the hat it wears (bought in Settings), and googly eyes
 * under brows that rise with each new tip. The eyes blink now and then and look toward the pointer, but under reduced
 * motion, which keeps them still.
 */
function Figure({ cue, hat }: { cue: string; hat: HatId | null }) {
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
