import { useLayoutEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'

import { headlinesFor, nextIndex, parseHeadline } from '@/lib/headlines'
import type { FlairColor, FlairEffect, Headline } from '@/lib/headlines'
import { SPEED_REM, useTickerSettings } from '@/lib/ticker-settings'
import { cn } from '@/lib/utils'

// RuneScape's chat colors and effects, as the utilities in src/index.css draw them, in the flair tokens.
const COLOR: Record<FlairColor, string> = {
    yellow: 'text-flair-yellow',
    red: 'text-flair-red',
    green: 'text-flair-green',
    cyan: 'text-flair-cyan',
    purple: 'text-flair-purple',
    white: 'text-foreground',
    flash1: 'flair-flash1',
    flash2: 'flair-flash2',
    flash3: 'flair-flash3',
    glow1: 'flair-glow1',
    glow2: 'flair-glow2',
    glow3: 'flair-glow3',
}

const EFFECT: Record<FlairEffect, string> = {
    wave: 'flair-wave',
    wave2: 'flair-wave2',
    shake: 'flair-shake',
}

/**
 * The header's news ticker: joke headlines, with tips mixed in, crawling right to left, one at a time, each picked at
 * random from the topics turned on. Each enters at the window's right edge and leaves at its left; the window then
 * stays empty for the gap set in Settings before the next arrives. It holds still under the pointer. Off, or with
 * every topic turned off, the space stays and the window is gone. Under reduced motion it shows its first headline in
 * place. A headline may carry RuneScape chat flair (`flash2:wave:`), drawn by `Flair`.
 */
export function Ticker() {
    const { speed, gap, hidden } = useTickerSettings()
    const headlines = headlinesFor(hidden)
    // Picked once per pass, never during render: a re-render mid-crawl must not swap the headline under the reader.
    // Turning a topic off shrinks the list, and the pick wraps onto what is left.
    const [pass, setPass] = useState(() => ({ n: 0, pick: nextIndex(headlines.length, -1) }))
    if (speed === 'off' || headlines.length === 0) {
        return <div className="min-w-0 flex-1" />
    }
    const index = pass.pick % headlines.length
    const headline = parseHeadline(headlines[index] ?? '')
    return (
        <div
            role="marquee"
            aria-label="Headlines"
            className="ticker-window flex min-w-0 flex-1 items-center"
            data-testid="ticker"
            data-speed={speed}
        >
            {/* Keyed on the settings too: a change restarts the crawl with the new settings rather than jumping. */}
            <Crawl
                key={`${pass.n}:${speed}:${gap}:${hidden.join()}`}
                headline={headline}
                rate={SPEED_REM[speed]}
                gap={gap}
                onDone={() => setPass({ n: pass.n + 1, pick: nextIndex(headlines.length, index) })}
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
function Crawl({ headline, rate, gap, onDone }: { headline: Headline; rate: number; gap: number; onDone: () => void }) {
    const line = useRef<HTMLSpanElement>(null)
    useLayoutEffect(() => {
        const element = line.current
        if (element === null) {
            return
        }
        const rem = Number.parseFloat(getComputedStyle(document.documentElement).fontSize)
        element.style.animationDuration = `${element.offsetWidth / (rate * rem)}s`
    }, [rate])
    const style = { '--ticker-gap': gap, '--ticker-rate': `${rate}rem` } as CSSProperties
    return (
        <span
            ref={line}
            className="animate-ticker shrink-0 text-xs whitespace-nowrap text-muted-foreground"
            style={style}
            onAnimationIteration={(event) => {
                // A flair's letters and colors loop too, and their iterations bubble up here: only the crawl's counts.
                if (event.target === event.currentTarget) {
                    onDone()
                }
            }}
            data-testid="ticker-headline"
        >
            <Flair headline={headline} />
        </span>
    )
}

/**
 * A headline in its flair: the color on the whole line, the effect on each letter. A line with an effect is read
 * once, as text, and drawn letter by letter for the eye alone.
 */
function Flair({ headline: { text, color, effect } }: { headline: Headline }) {
    const tone = color && COLOR[color]
    if (effect === undefined) {
        return <span className={tone}>{text}</span>
    }
    return (
        <>
            <span className="sr-only">{text}</span>
            <span aria-hidden className={tone}>
                {Array.from(text, (letter, i) => (
                    <span key={i} className={cn('flair-letter', EFFECT[effect])} style={{ '--i': i } as CSSProperties}>
                        {letter}
                    </span>
                ))}
            </span>
        </>
    )
}
