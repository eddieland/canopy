import { type CSSProperties, useLayoutEffect, useRef, useState } from 'react'

import { headlinesFor } from '@/lib/headlines'
import { SPEED_REM, useTickerSettings } from '@/lib/ticker-settings'

/**
 * The header's news ticker: joke headlines crawling right to left, one at a time. Each enters at the window's right
 * edge and leaves at its left; the window then stays empty for the gap set in Settings before the next arrives. It
 * holds still under the pointer. Off, the space stays and the window is gone. Under reduced motion it shows the first
 * headline in place.
 */
export function Ticker() {
    const { speed, gap } = useTickerSettings()
    // Picked once per page load: a re-render mid-crawl must not reorder the reel under the reader.
    const [headlines] = useState(() => headlinesFor(Date.now()))
    const [index, setIndex] = useState(0)
    if (speed === 'off') return <div className="min-w-0 flex-1" />
    const text = headlines[index % headlines.length] ?? ''
    return (
        <div
            role="marquee"
            aria-label="Headlines"
            className="ticker-window flex min-w-0 flex-1 items-center"
            data-testid="ticker"
            data-speed={speed}
        >
            {/* Keyed on the settings too: a change restarts the crawl at the new pace rather than jumping. */}
            <Crawl
                key={`${index}:${speed}:${gap}`}
                text={text}
                rate={SPEED_REM[speed]}
                gap={gap}
                onDone={() => setIndex((i) => i + 1)}
            />
        </div>
    )
}

/**
 * One headline's pass. The line is padded by the window's width before the text and the gap's distance after it, and
 * slides its own width: in from the right, out to the left, then the gap's worth of empty window. The duration is
 * that width over the rate, so every headline moves at the same pace. The crawl loops, and the first loop's end
 * moves on to the next headline, so a screenshot that freezes animations sees one still frame.
 */
function Crawl({ text, rate, gap, onDone }: { text: string; rate: number; gap: number; onDone: () => void }) {
    const line = useRef<HTMLSpanElement>(null)
    useLayoutEffect(() => {
        const element = line.current
        if (element === null) return
        const rem = Number.parseFloat(getComputedStyle(document.documentElement).fontSize)
        element.style.animationDuration = `${element.offsetWidth / (rate * rem)}s`
    }, [rate])
    const style = { '--ticker-gap': gap, '--ticker-rate': `${rate}rem` } as CSSProperties
    return (
        <span
            ref={line}
            className="animate-ticker shrink-0 text-xs whitespace-nowrap text-muted-foreground"
            style={style}
            onAnimationIteration={onDone}
            data-testid="ticker-headline"
        >
            {text}
        </span>
    )
}
