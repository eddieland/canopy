import { type CSSProperties, useState } from 'react'

import { headlinesFor } from '@/lib/headlines'

// How long the crawl spends on each character of one pass: a steady reading pace, whatever the headlines' length.
const SECONDS_PER_CHAR = 0.1

/**
 * The header's news ticker: joke headlines crawling right to left, holding still under the pointer. Two copies of the
 * reel sit end to end and the strip slides one copy's width, so the loop has no seam. Under reduced motion it rests
 * on the first headlines.
 */
export function Ticker() {
    // Picked once per page load: a re-render mid-crawl must not reorder the reel under the reader.
    const [headlines] = useState(() => headlinesFor(Date.now()))
    const chars = headlines.reduce((sum, line) => sum + line.length + 5, 0)
    const style = { '--ticker-duration': `${Math.round(chars * SECONDS_PER_CHAR)}s` } as CSSProperties
    return (
        <div role="marquee" aria-label="Headlines" className="ticker-window min-w-0 flex-1" data-testid="ticker">
            <div className="animate-ticker flex w-max" style={style}>
                <Reel headlines={headlines} />
                <Reel headlines={headlines} hidden />
            </div>
        </div>
    )
}

function Reel({ headlines, hidden = false }: { headlines: string[]; hidden?: boolean }) {
    return (
        <ul aria-hidden={hidden || undefined} className="flex shrink-0 items-center">
            {headlines.map((line) => (
                <li key={line} className="flex items-center text-xs whitespace-nowrap text-muted-foreground">
                    {line}
                    <span aria-hidden className="px-4 opacity-50">
                        &#x2726;
                    </span>
                </li>
            ))}
        </ul>
    )
}
