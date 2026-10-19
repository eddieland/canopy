// The browser tab's icon (ui/DESIGN.md, "The tab"). A pinned tab shows no title, so the count `pageTitle` leads with is
// lost there; the icon is all it shows. While anything blocks on the operator, a dot on the icon's corner says so, in
// the most severe item's color.

import type { AttentionItem } from '@/api/types'
import { blocking, bySeverity, severity } from '@/lib/attention'

/** What the tab's dot says: the severity of the most severe item that blocks work. A finding never blocks. */
export type FaviconDot = 'failed' | 'waiting' | 'other'

/** The colors the icon is drawn in, each a CSS color read from a token, so the icon follows the theme. */
export interface FaviconColors {
    /** The mark's ring and dot: the accent. */
    mark: string
    /** The dot on the corner, by what it says: the failure color, the color of what waits on the operator, muted. */
    dot: Record<FaviconDot, string>
}

/**
 * The dot the tab's icon wears for `items`: the severity of the most severe item that blocks work, the items the tab's
 * count counts, or null when none does or the list has not been read.
 */
export function faviconDot(items: readonly AttentionItem[] | undefined): FaviconDot | null {
    const first = bySeverity((items ?? []).filter((item) => blocking(item)))[0]
    if (first === undefined) {
        return null
    }
    const said = severity(first)
    return said === 'finding' ? null : said
}

/**
 * The tab's icon as an SVG document: the header's mark (src/components/shell/mark.tsx) in `colors.mark`, and `dot` on
 * its top right corner, cut out of the ring so it reads apart from it on any tab strip.
 */
export function faviconSvg(dot: FaviconDot | null, colors: FaviconColors): string {
    const mark =
        `<circle cx="8" cy="8" r="6.25" fill="none" stroke="${colors.mark}" stroke-width="1.5"/>` +
        `<circle cx="8" cy="8" r="2" fill="${colors.mark}"/>`
    const body = dot === null ? mark : `<g mask="url(#m)">${mark}</g>${corner(colors.dot[dot])}`
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">${body}</svg>`
}

// The corner's dot in `color`, and the mask that hides the mark under it and a gap around it.
function corner(color: string): string {
    return (
        '<mask id="m"><rect width="16" height="16" fill="white"/><circle cx="12.75" cy="3.25" r="4.5" fill="black"/>' +
        `</mask><circle cx="12.75" cy="3.25" r="3.25" fill="${color}"/>`
    )
}

/** The icon as a `data:` URL for a `<link rel="icon">`, which the CSP's `img-src` allows (canopy/serve/spa.py). */
export function faviconUrl(dot: FaviconDot | null, colors: FaviconColors): string {
    return `data:image/svg+xml,${encodeURIComponent(faviconSvg(dot, colors))}`
}
