import { useRouterState } from '@tanstack/react-router'
import { X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { sectionOf, setBuddy, tipFor } from '@/lib/buddy'
import type { Section } from '@/lib/buddy'
import { cn } from '@/lib/utils'

/** How long a tip stays up before Sprig takes the hint. */
const TIP_SECONDS = 20

/**
 * Sprig, the helper in the bottom-left corner, in the side rail under the nav and above its footer, where it covers
 * nothing: a bent wire with a sprig on top and googly eyes that follow the pointer. On every page it offers a tip
 * about that page, the dumber the better (`TIPS` in src/lib/buddy.ts); clicking it offers another. The tip closes with
 * its button, or by itself after a while. Settings turns Sprig off, and so does the tip's "Don't show me tips again".
 */
export function Buddy() {
    const pathname = useRouterState({ select: (state) => state.location.pathname })
    const section = sectionOf(pathname)
    // Read once per page load, as the ticker's reel is: the tip must not change under the reader.
    const [today] = useState(() => Date.now())
    // How many more tips the reader asked for, counted per section: a new section starts at its own first tip.
    const [asked, setAsked] = useState<{ section: Section | undefined; n: number }>({ section, n: 0 })
    const n = asked.section === section ? asked.n : 0
    const another = () => setAsked({ section, n: n + 1 })
    const tip = tipFor(pathname, n, today)
    // A different tip opens a new bubble: the key remounts it, open, and raises Sprig's brows. A page that offers the
    // tip already shown (another of the section's pages) leaves the bubble as it is, open or closed.
    return (
        <aside
            aria-label="Sprig"
            data-testid="buddy"
            className="pointer-events-none fixed bottom-12 left-3 z-20 flex w-48 flex-col items-start gap-2"
        >
            <Bubble key={tip} tip={tip} onAnother={another} />
            <button
                type="button"
                aria-label="Ask Sprig for a tip"
                data-testid="buddy-sprig"
                onClick={another}
                className={cn(
                    'pointer-events-auto rounded-md p-1 transition-transform',
                    'outline-none focus-visible:ring-2 focus-visible:ring-ring motion-safe:hover:-translate-y-0.5',
                )}
            >
                <Figure cue={tip} />
            </button>
        </aside>
    )
}

/** The speech bubble above Sprig: the tip, another, and the way out. Its tail points down at Sprig. */
function Bubble({ tip, onAnother }: { tip: string; onAnother: () => void }) {
    const [open, setOpen] = useState(true)
    useEffect(() => {
        const timer = globalThis.setTimeout(() => setOpen(false), TIP_SECONDS * 1000)
        return () => globalThis.clearTimeout(timer)
    }, [])
    if (!open) {
        return null
    }
    return (
        <div
            data-testid="buddy-tip"
            className={cn(
                'animate-buddy-tip pointer-events-auto relative w-full rounded-md border bg-surface-raised p-3',
                'text-sm',
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
 * Sprig itself: a paperclip's bent wire, a sprig of leaf on top, and googly eyes under brows that rise with each new
 * tip. The eyes blink now and then and look toward the pointer, but under reduced motion, which keeps them still.
 */
function Figure({ cue }: { cue: string }) {
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
