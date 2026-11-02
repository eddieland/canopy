import { useRouterState } from '@tanstack/react-router'
import { X } from 'lucide-react'
import { useEffect, useEffectEvent, useRef, useState } from 'react'
import type { CSSProperties, RefObject } from 'react'

import { ShellCrest, ShellEye, ShellPlates, ShellRing } from '@/components/ghost-shell'
import { HatDrawing } from '@/components/hat'
import { SeasonDecoration } from '@/components/season'
import { useFits } from '@/hooks/use-fits'
import { useMediaQuery } from '@/hooks/use-media-query'
import { NAMES, nextTip, setBuddy, tipsFor, typeBurst, useCompanion } from '@/lib/buddy'
import type { Companion, View } from '@/lib/buddy'
import { HIGH_SKY, LOW_SKY, inSky, nextLeg } from '@/lib/ghost-flight'
import type { Spot } from '@/lib/ghost-flight'
import { useWardrobe } from '@/lib/hats'
import type { HatId } from '@/lib/hats'
import { onRaveStart, useRave } from '@/lib/rave'
import { useSeason } from '@/lib/seasons'
import { useVault } from '@/lib/shells'
import type { ShellId } from '@/lib/shells'
import { cn } from '@/lib/utils'
import type { FileRoutesById } from '@/routeTree.gen'

/** How long a tip stays up before Sprig takes the hint. */
const TIP_SECONDS = 20
/** The shortest and longest Sprig waits, after a tip closes, before offering the next unasked: picked at random. */
const WAIT_SECONDS = { least: 120, most: 360 }
/**
 * How far Sprig may stand over the foot of the rail's top, what is working, in a rail too short to hold it whole: the
 * top's 12px of padding under its last block, then a little of that block's last row.
 */
const OVERLAP_PX = 40

/**
 * How Sprig fits its slot: `roomy`, with the room for its bubble too, or tight, only for itself, standing over what is
 * working by the number of pixels given, which is zero when its bubble's room alone rises over it.
 */
type Room = 'roomy' | number

/** The tip Sprig last offered: who offered it, on which view, what it says, whether it is up, and if it was asked. */
interface Offer {
    /** Who offered it, Sprig or the Ghost in its place, in whose voice it is. */
    companion: Companion
    /** The view it was offered on, which it is about. */
    view: View | undefined
    /** Whether it was offered while the lightswitch rave was on, which it is then about instead. */
    rave: boolean
    /** How many tips came before it, since the page loaded: a new count pops a new bubble in. */
    n: number
    /** What it says: picked at random as it is offered (`nextTip`), and kept, so it never changes under the reader. */
    tip: string
    /** Whether its bubble is up, till it is closed or its time runs out. */
    open: boolean
    /** Whether the reader asked for it with a click, rather than Sprig offering it on its own. */
    asked: boolean
}

/**
 * Sprig, the helper at the foot of the side rail: a bent wire with a sprig on top and googly eyes that follow the
 * pointer. Now and then, at random, it offers a tip about the view on screen, the dumber the better (`TIPS` in
 * src/lib/buddy.ts), each picked at random, as the ticker's headlines are; clicking it offers another at once. Its
 * clock is its own: turning a page neither offers a tip nor puts the next one off, and a tip offered on one view is not
 * shown on another. The tip closes with its button, or by itself after a while, and the next comes a few minutes after
 * that. Settings turns Sprig off, and so does the tip's "Don't show me tips again".
 *
 * While the lightswitch rave is on (src/components/shell/rave.tsx), Sprig dances on its beat and talks of nothing else
 * (`RAVE`): the lights going off offers a tip about them at once, a tip from before the rave is hidden, and so is a
 * rave tip once the lights come back on.
 *
 * It has a slot of its own in the rail's column, between its top and its foot: the slot is the one gap left between
 * what is working and the spend, and Sprig stands at its foot, on the spend's hairline. A slot with room for Sprig and
 * its bubble covers nothing. A shorter one, as a laptop's window leaves, still shows Sprig if it can stand over the
 * foot of what is working by `OVERLAP_PX` or less, as the operator asked; there the bubble would cover the blocks
 * above, so a tip shows only when asked for, with a click, and Sprig lets the ones it would offer on its own pass. A
 * slot shorter still leaves Sprig out, rather than squeeze the blocks above. Whatever Sprig stands over still takes
 * its clicks: Sprig is clicked only within its slot, and a tip only while it shows.
 *
 * Settings can put a Ghost in Sprig's place: it floats where Sprig stands, in a voice of its own
 * (src/lib/ghost.ts), and keeps every rule above. A tip one of them offered is never shown under the other's name.
 *
 * In a season (src/lib/seasons.ts), unless Settings has the seasons off, a jack-o'-lantern or the like stands beside
 * whichever of them is there, in the same slot, so it steps out with them; what hangs or flies over it shows only
 * where the bubble has its room, so it never covers the blocks above. With Sprig off, the season stands there alone
 * (src/components/shell/season-slot.tsx).
 */
export function Buddy() {
    const view = viewOf(useRouterState({ select: (state) => state.matches.at(-1)?.routeId }))
    const rave = useRave() === 'on'
    const companion = useCompanion()
    const name = NAMES[companion]
    // Closed until the first is offered, the bubble holding a tip's room meanwhile.
    const [offer, setOffer] = useState<Offer>(() => ({
        companion,
        view,
        rave,
        n: 0,
        tip: nextTip(tipsFor(view, rave, companion), ''),
        open: false,
        asked: false,
    }))
    const [slot, room] = useFits(roomFor)
    const { worn } = useWardrobe()
    const shell = useVault().worn
    const season = useSeason()
    // Offers the next tip, about the view on screen or the rave, never the one just offered.
    const offerNext = (asked: boolean, raving: boolean) =>
        setOffer({
            companion,
            view,
            rave: raving,
            n: offer.n + 1,
            tip: nextTip(tipsFor(view, raving, companion), offer.tip),
            open: true,
            asked,
        })
    const another = () => offerNext(true, rave)
    const tight = typeof room === 'number'
    // Offers the next tip unasked, when the time comes, if the bubble would cover nothing and the tab is in sight to
    // read it. A rave just started is on before Sprig renders it, so it is said.
    const offerUnasked = useEffectEvent((raving: boolean = rave) => {
        if (room === 'roomy' && document.visibilityState === 'visible') {
            offerNext(false, raving)
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
    // The lights going off is worth a word at once: not a page loading with them off, only the switch flipped since.
    useEffect(() => onRaveStart(() => offerUnasked(true)), [])
    const shown =
        offer.open &&
        offer.companion === companion &&
        offer.view === view &&
        offer.rave === rave &&
        (room === 'roomy' || offer.asked)
    // A new tip opens a new bubble: the key remounts it, popping it in, and raises Sprig's brows. Closed, the bubble
    // keeps the last tip's room, whatever the page, so Sprig does not move. Sprig, and a bubble shown in a tight slot,
    // rise out of the slot over the blocks above: positioned, so they paint over them. What they rise over is still
    // clicked: the aside takes no pointer, only a tip that shows does, and Sprig only within its slot.
    return (
        <div ref={slot} className="flex min-h-0 flex-1 flex-col justify-end print:hidden">
            <aside
                aria-label={name}
                data-testid="buddy"
                data-room={room === false ? undefined : tight ? 'tight' : room}
                className={cn(
                    'pointer-events-none relative flex shrink-0 flex-col items-start gap-2 px-2 pt-3 pb-1',
                    room === false && 'invisible',
                )}
            >
                <Bubble
                    key={offer.n}
                    name={name}
                    tip={offer.tip}
                    open={offer.open}
                    shown={shown}
                    onAnother={another}
                    onClose={close}
                />
                {/* Sprig and, in a season, what stands beside it on the same floor; the row is the figure roomFor
                    measures, as tall as Sprig. */}
                <div className="flex items-end gap-1">
                    <button
                        type="button"
                        aria-label={`Ask ${name} for a tip`}
                        data-testid="buddy-sprig"
                        onClick={another}
                        className={cn(
                            'relative rounded-md p-1 transition-transform outline-none',
                            'focus-visible:ring-2 focus-visible:ring-ring motion-safe:hover:-translate-y-0.5',
                        )}
                    >
                        {companion === 'ghost' ? (
                            <GhostFigure cue={offer.n} rave={rave} shell={shell} soar={room === 'roomy' && !shown} />
                        ) : (
                            <Figure cue={offer.n} hat={worn} rave={rave} />
                        )}
                        {/* Where Sprig takes a click: all of it but what rises over the blocks above. */}
                        <span
                            aria-hidden
                            className="pointer-events-auto absolute inset-x-0 bottom-0"
                            style={{ top: tight ? room : 0 }}
                        />
                    </button>
                    {season === null ? null : <SeasonDecoration id={season} aloft={room === 'roomy'} />}
                </div>
            </aside>
        </div>
    )
}

/**
 * The view a route is: every route but those that only redirect, the root and the guide's. Returning the route as a
 * view is what holds `TIPS` to the routes, so a new route fails the type check until it has tips of its own.
 */
function viewOf(routeId: keyof FileRoutesById | undefined): View | undefined {
    return routeId === undefined ||
        routeId === '__root__' ||
        routeId === '/' ||
        routeId === '/spend' ||
        routeId === '/reviews/' ||
        routeId === '/reviews/$id' ||
        routeId === '/reviews/$id_/run' ||
        routeId === '/ticks/' ||
        routeId === '/ticks/$id' ||
        routeId === '/worktrees' ||
        routeId === '/runs/' ||
        routeId === '/runs/$id' ||
        routeId === '/runs/ticks/' ||
        routeId === '/runs/ticks/$id' ||
        routeId === '/runs/worktrees' ||
        routeId === '/guide/'
        ? undefined
        : routeId
}

/**
 * How Sprig, the slot's one child, fits: whole, its bubble included, or the figure alone once it may stand over the
 * blocks above by `OVERLAP_PX`, with how far its button does. False for neither.
 */
function roomFor(slot: HTMLElement): Room | false {
    const sprig = slot.firstElementChild
    const figure = sprig?.lastElementChild
    const button = figure?.firstElementChild
    if (!(sprig instanceof HTMLElement) || !(figure instanceof HTMLElement) || !(button instanceof HTMLElement)) {
        return false
    }
    if (sprig.offsetHeight <= slot.clientHeight) {
        return 'roomy'
    }
    // From the figure's top, and the button's, to Sprig's foot: the aside is positioned, so it is their offsetParent.
    if (sprig.offsetHeight - figure.offsetTop > slot.clientHeight + OVERLAP_PX) {
        return false
    }
    return Math.max(0, sprig.offsetHeight - button.offsetTop - slot.clientHeight)
}

/**
 * The speech bubble above Sprig: the tip, another, and the way out. Its tail points down at Sprig. It closes itself
 * once its tip has been up a while, counted from when it opened, shown or not: a tip is only offered where it shows.
 * Not `shown`, it is hidden but keeps its room, so Sprig does not move.
 */
function Bubble({
    name,
    tip,
    open,
    shown,
    onAnother,
    onClose,
}: {
    name: string
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
                'animate-buddy-tip pointer-events-auto relative w-full rounded-md border bg-surface-raised p-3 text-sm',
                !shown && 'invisible',
            )}
        >
            <p className="panel-label mb-1">{name}</p>
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
                    title={`Turns ${name} off. Settings turns it back on.`}
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
 * now and then and look toward the pointer, and the keys are typed on in bursts. While the lightswitch rave is on,
 * all of it but the keyboard dances on its foot, on the lights' beat, waving a glow stick each side. Under reduced
 * motion all of it holds still.
 */
function Figure({ cue, hat, rave }: { cue: number; hat: HatId | null; rave: boolean }) {
    const figure = useRef<SVGSVGElement>(null)
    useEyesOnPointer(figure, 2.5)
    return (
        <svg ref={figure} viewBox="0 -6 48 92" className="h-24 w-[3.25rem] overflow-visible" aria-hidden>
            {/* Drawn before the keyboard, which stays put in front of its foot while it dances. */}
            <g data-testid="buddy-body" className={cn(rave && 'animate-buddy-dance')}>
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
                {rave ? <GlowSticks /> : null}
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
            </g>
            <Keyboard />
        </svg>
    )
}

/**
 * Turns the pupil of each eye in `figure` (its `[data-eye]` groups, each with a `[data-pupil]`) toward the pointer, at
 * most `most` units off center, in the drawing's own units, and less for a pointer close by. Under reduced motion they
 * hold still.
 */
function useEyesOnPointer(figure: RefObject<SVGSVGElement | null>, most: number): void {
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
                const reach = most * Math.min(1, distance / 120)
                const x = ((dx / distance) * reach).toFixed(2)
                const y = ((dy / distance) * reach).toFixed(2)
                eye.querySelector('[data-pupil]')?.setAttribute('transform', `translate(${x} ${y})`)
            }
        }
        globalThis.addEventListener('pointermove', look, { passive: true })
        return () => globalThis.removeEventListener('pointermove', look)
    }, [figure, most])
}

/**
 * The Ghost that may sit in Sprig's place, in the shell it wears (bought in Settings; src/components/ghost-shell.tsx):
 * four great plates around one glowing eye, four lesser ones behind them on the diagonals, flying about its corner of
 * the rail over its shadow (`useFlight`), and bobbing as it goes. Its light swells and dims, and flares with each new
 * tip. The eye blinks now and then and looks toward the pointer, and the great plates spread a little with each tip, as
 * it talks. While `soar` is on, the rail has room and no tip is up, so it may fly high. While the lightswitch rave is
 * on, its shell turns a quarter on each beat of the lights, and its light swells in time. Under reduced motion all of
 * it holds still.
 */
function GhostFigure({ cue, rave, shell, soar }: { cue: number; rave: boolean; shell: ShellId; soar: boolean }) {
    const figure = useRef<SVGSVGElement>(null)
    const body = useRef<SVGGElement>(null)
    const shadow = useRef<SVGGElement>(null)
    useEyesOnPointer(figure, 1.8)
    useFlight(body, shadow, soar)
    return (
        <svg ref={figure} viewBox="0 -6 48 92" className="h-24 w-[3.25rem] overflow-visible" aria-hidden>
            <g ref={shadow} className="origin-center transform-fill">
                <ellipse cx="24" cy="76" rx="11" ry="2" className="animate-ghost-shadow fill-buddy-ghost-facet/30" />
            </g>
            <g ref={body} className="origin-center transform-fill">
                <g data-testid="ghost-body" className="animate-ghost-float">
                    <ShellPlates id={shell} cue={cue} rave={rave} />
                    <ShellCrest id={shell} />
                    <ShellRing id={shell} />
                    <ShellEye id={shell} cue={cue} rave={rave} />
                </g>
            </g>
        </svg>
    )
}

/** How long the Ghost waits, once it shows, before its first leg, in milliseconds. */
const FIRST_LEG_MS = 1200
/**
 * How long each leg's animation holds where it ended past when the next leg is due, in milliseconds, so a timer that
 * fires late never shows it start the leg over.
 */
const HOLD_MS = 1000
/** How much smaller and fainter the Ghost's shadow is at the top of its high sky. */
const SHADOW_AT_TOP = { scale: 0.45, opacity: 0.4 }

/**
 * Flies the Ghost's `body` about its corner of the rail, a leg at a time (src/lib/ghost-flight.ts), over its `shadow`,
 * which follows it along the floor and shrinks and fades as it rises. While `soar` is off its sky is low, and a Ghost
 * flying high comes down as soon as the leg it is on ends. Each leg is an animation that repeats until the next
 * replaces it, which a page that stops its animations, as a screenshot does, puts back where it rests. Under reduced
 * motion it holds still where it rests.
 */
function useFlight(body: RefObject<SVGGElement | null>, shadow: RefObject<SVGGElement | null>, soar: boolean): void {
    const still = useMediaQuery('(prefers-reduced-motion: reduce)')
    const sky = useEffectEvent(() => (soar ? HIGH_SKY : LOW_SKY))
    // Brings the Ghost down into a sky that came down, once the leg it is on ends; set while it flies.
    const comeDown = useRef<(() => void) | null>(null)
    useEffect(() => {
        const flier = body.current
        const floor = shadow.current
        if (flier === null || floor === null || still) {
            return
        }
        let at: Spot = { x: 0, y: 0 }
        let flying: Animation[] = []
        let timer: ReturnType<typeof globalThis.setTimeout> | undefined
        // When the leg flying now lands.
        let lands = 0
        const fly = () => {
            const leg = nextLeg(at, sky())
            const span = leg.ms + leg.rest + HOLD_MS
            const landed = leg.ms / span
            const timing = { duration: span, iterations: Number.POSITIVE_INFINITY }
            const easing = leg.dart ? 'cubic-bezier(0.2, 0, 0, 1)' : 'ease-in-out'
            const next = [
                flier.animate(
                    [
                        { translate: place(at), rotate: '0deg', easing },
                        { rotate: `${leg.lean.toFixed(1)}deg`, offset: landed * 0.45, easing: 'ease-in-out' },
                        { translate: place(leg.to), rotate: '0deg', offset: landed },
                        { translate: place(leg.to), rotate: '0deg' },
                    ],
                    { ...timing, id: 'ghost-flight' },
                ),
                floor.animate([{ ...onFloor(at), easing }, { ...onFloor(leg.to), offset: landed }, onFloor(leg.to)], {
                    ...timing,
                    id: 'ghost-flight-shadow',
                }),
            ]
            for (const animation of flying) {
                animation.cancel()
            }
            flying = next
            at = leg.to
            lands = performance.now() + leg.ms
            timer = globalThis.setTimeout(fly, leg.ms + leg.rest)
        }
        timer = globalThis.setTimeout(fly, FIRST_LEG_MS)
        comeDown.current = () => {
            if (!inSky(at, sky())) {
                globalThis.clearTimeout(timer)
                timer = globalThis.setTimeout(fly, Math.max(0, lands - performance.now()))
            }
        }
        return () => {
            globalThis.clearTimeout(timer)
            for (const animation of flying) {
                animation.cancel()
            }
            comeDown.current = null
        }
    }, [body, shadow, still])
    useEffect(() => {
        if (!soar) {
            comeDown.current?.()
        }
    }, [soar])
}

/** Where the Ghost is at `spot`, as a CSS `translate`. */
function place(spot: Spot): string {
    return `${spot.x}px ${spot.y}px`
}

/** Its shadow under `spot`: along the floor beneath it, smaller and fainter the higher it is. */
function onFloor(spot: Spot): { translate: string; scale: string; opacity: string } {
    const height = Math.min(1, -spot.y / HIGH_SKY.rise)
    return {
        translate: `${spot.x}px 0px`,
        scale: (1 - height * (1 - SHADOW_AT_TOP.scale)).toFixed(3),
        opacity: (1 - height * (1 - SHADOW_AT_TOP.opacity)).toFixed(3),
    }
}

/**
 * Sprig's glow sticks, out while the lightswitch rave is on: one each side of the wire, held where it touches them and
 * raised outwards, a bright core in a soft glow of its color. Both turn the same way from their grips, in time with
 * the lights, so as one sweeps out the other comes in.
 */
const STICKS = [
    { d: 'M8 50 L0 38', grip: 'bottom right', color: 'text-flair-green' },
    { d: 'M40 50 L48 38', grip: 'bottom left', color: 'text-flair-purple' },
] as const

/** The glow sticks Sprig waves at the rave (`STICKS`). */
function GlowSticks() {
    return (
        <g data-testid="buddy-glow-sticks">
            {STICKS.map((stick) => (
                <g
                    key={stick.grip}
                    className={cn('animate-buddy-wave', stick.color)}
                    style={{ '--grip': stick.grip } as CSSProperties}
                >
                    <path d={stick.d} stroke="currentColor" strokeWidth="5" strokeOpacity="0.3" strokeLinecap="round" />
                    <path d={stick.d} stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                </g>
            ))}
        </g>
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
/** The space bar, as its row and its place in the row: every burst ends on it. */
const SPACE = '2-2'
/** Every other key, the same way: the keys a burst picks from (`typeBurst`). */
const LETTERS = ROWS.flatMap((row, r) => row.keys.map((_, k) => `${r}-${k}`)).filter((key) => key !== SPACE)

/**
 * The keyboard Sprig vibe codes on, in front of the foot of its wire: a case seen from above, three rows of keys, the
 * last a space bar. A few keys light in the accent as Sprig types on them, a burst every few seconds, different keys
 * each time: when the first key's press ends its animation, the keys remount with the next burst's.
 */
function Keyboard() {
    const [burst, setBurst] = useState(() => ({ n: 0, typed: typeBurst(LETTERS, SPACE) }))
    return (
        <g data-keyboard>
            <path
                d={CASE}
                strokeWidth="1"
                strokeLinejoin="round"
                className="fill-buddy-keyboard stroke-buddy-keyboard"
            />
            <g key={burst.n} onAnimationEnd={() => setBurst({ n: burst.n + 1, typed: typeBurst(LETTERS, SPACE) })}>
                {ROWS.map((row, r) =>
                    keysOf(row).map((key, k) => {
                        const typed = burst.typed.indexOf(`${r}-${k}`)
                        return (
                            <rect
                                key={`${r}-${k}`}
                                x={key.x}
                                y={row.y}
                                width={key.width}
                                height={KEY.height}
                                rx="0.4"
                                className={cn('fill-buddy-key', typed !== -1 && 'animate-buddy-key')}
                                style={typed === -1 ? undefined : ({ '--key': typed } as CSSProperties)}
                            />
                        )
                    }),
                )}
            </g>
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
