import { useEffect, useState } from 'react'

import type { DiffFile } from '@/api/types'
import type { CodeToken } from '@/lib/highlight'
import { highlightLanguage } from '@/lib/languages'

/**
 * The tokens of each line of `file`'s hunks, by hunk and then line, once its language's grammar has loaded and read
 * them (`src/lib/highlight.ts`); undefined until then, and for good when the file is in no language canopy highlights,
 * is too long to highlight (`highlightLanguage`), or the highlighter fails, so its lines stay plain text, the same
 * characters in the same place.
 */
export function useHighlight(file: DiffFile): (CodeToken[] | undefined)[][] | undefined {
    const [done, setDone] = useState<{ file: DiffFile; hunks: (CodeToken[] | undefined)[][] }>()
    useEffect(() => {
        const language = highlightLanguage(file)
        // Aborted when the file changes or the diff leaves the page, so a late result is dropped.
        const gone = new AbortController()
        if (language !== undefined && file.hunks.length > 0) {
            void (async () => {
                try {
                    const { highlightHunks } = await import('@/lib/highlight')
                    const hunks = await highlightHunks(language, file.hunks)
                    if (!gone.signal.aborted) {
                        setDone({ file, hunks })
                    }
                } catch {
                    // Highlighting is a nicety: a grammar that fails to load or read leaves the diff as it was.
                }
            })()
        }
        return () => gone.abort()
    }, [file])
    return done?.file === file ? done.hunks : undefined
}
