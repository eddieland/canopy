import { useEffect, useState } from 'react'

import type { Drawn, NotDrawn } from '@/lib/diagram'

/**
 * `source`, a Mermaid diagram, drawn (`src/lib/diagram.ts`, which loads mermaid only now): undefined while it is drawn
 * the first time, then its SVG or why it was not drawn. `look` names the theme and palettes the page shows, so a change
 * to them draws it again in their colors, the old picture shown until the new one is ready.
 */
export function useDiagram(source: string, look: string): Drawn | NotDrawn | undefined {
    // Each picture keeps the source and the look it was drawn in.
    const [done, setDone] = useState<{ source: string; look: string; result: Drawn | NotDrawn }>()
    useEffect(() => {
        // Aborted when the source or the look changes, or the diagram leaves the page, so a late result is dropped.
        const gone = new AbortController()
        void (async () => {
            let result: Drawn | NotDrawn
            try {
                const { drawDiagram } = await import('@/lib/diagram')
                result = await drawDiagram(source)
            } catch (error) {
                result = { error: `it could not be drawn: ${String(error)}` }
            }
            if (!gone.signal.aborted) {
                setDone({ source, look, result })
            }
        })()
        return () => gone.abort()
    }, [source, look])
    return done?.source === source ? done.result : undefined
}
