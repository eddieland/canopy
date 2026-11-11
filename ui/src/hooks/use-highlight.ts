import { useEffect, useState } from 'react'

import type { DiffFile } from '@/api/types'
import type { CodeToken } from '@/lib/highlight'
import { highlightLanguage } from '@/lib/languages'
import type { Language } from '@/lib/languages'

// Loads the highlighter's module when the first code is read. Outside the hooks: the React Compiler does not compile
// a dynamic `import()`, and would leave a hook that held one unmemoized (`react/todo` in the lint).
const loadHighlighter = () => import('@/lib/highlight')

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
                    const { highlightHunks } = await loadHighlighter()
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

/**
 * The tokens of each of `lines`, a code block's, read whole in `language` (`src/lib/highlight.ts`); undefined until its
 * grammar has loaded and read them, and for good when it names no language canopy highlights or the highlighter fails,
 * so the block stays plain text, the same characters in the same place.
 */
export function useHighlightLines(
    language: Language | undefined,
    lines: readonly string[],
): (CodeToken[] | undefined)[] | undefined {
    // Read by its text, so a block parsed again into a new array, with the same lines, is not read again.
    const text = lines.join('\n')
    const [done, setDone] = useState<{ language: Language; text: string; lines: (CodeToken[] | undefined)[] }>()
    useEffect(() => {
        const gone = new AbortController()
        if (language !== undefined) {
            void (async () => {
                try {
                    const { highlightLines } = await loadHighlighter()
                    const tokens = await highlightLines(language, text.split('\n'))
                    if (!gone.signal.aborted) {
                        setDone({ language, text, lines: tokens })
                    }
                } catch {
                    // As a diff's: a grammar that fails leaves the block as it was.
                }
            })()
        }
        return () => gone.abort()
    }, [language, text])
    return done !== undefined && done.language === language && done.text === text ? done.lines : undefined
}
