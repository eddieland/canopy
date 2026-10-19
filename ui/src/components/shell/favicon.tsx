import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'

import { attentionQuery } from '@/api/queries'
import { faviconDot, faviconUrl } from '@/lib/favicon'
import type { FaviconColors, FaviconDot } from '@/lib/favicon'
import { useTheme } from '@/theme/use-theme'

/**
 * Draws the browser tab's icon while signed in: the header's mark in the accent, with a dot on its corner in the most
 * severe blocking item's color while anything blocks on the operator (`faviconDot`), the items the tab's title counts.
 * It renders nothing; it rewrites index.html's `<link rel="icon">`, and puts back what it held on unmount, so the
 * sign-in page shows the plain mark. Its colors are the theme's tokens, drawn again when the theme changes.
 */
export function Favicon() {
    const dot = faviconDot(useQuery(attentionQuery).data)
    // A new theme draws the icon anew, reading the tokens it resolves to.
    return <TabIcon key={useTheme().resolved} dot={dot} />
}

function TabIcon({ dot }: { dot: FaviconDot | null }) {
    useEffect(() => {
        const link = document.querySelector<HTMLLinkElement>('link[rel~="icon"]')
        if (link === null) {
            return
        }
        const before = link.getAttribute('href')
        link.href = faviconUrl(dot, colors())
        return () => {
            if (before !== null) {
                link.setAttribute('href', before)
            }
        }
    }, [dot])
    return null
}

// The tokens as the theme on <html> resolves them; the store applies a theme before it tells React of it.
function colors(): FaviconColors {
    const style = getComputedStyle(document.documentElement)
    const token = (name: string) => style.getPropertyValue(name).trim()
    return {
        mark: token('--accent'),
        dot: {
            failed: token('--status-failed'),
            waiting: token('--status-blocked'),
            other: token('--muted-foreground'),
        },
    }
}
