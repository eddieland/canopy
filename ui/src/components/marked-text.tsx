import type { ReactNode } from 'react'

import { marked } from '@/lib/search'

/**
 * `text` with each match of any of `words` marked (`marked`, `src/lib/search.ts`): a search's hits, in a snippet or a
 * transcript's line. All of it is React text, never markup.
 */
export function MarkedText({ text, words }: { text: string; words: readonly string[] }) {
    // A text's pieces never reorder, so their index is their key.
    return marked(text, words).map((piece, i) => (piece.mark ? <Mark key={i}>{piece.text}</Mark> : piece.text))
}

/** One match, on the accent's tint. What it wraps keeps its own color; plain text takes the foreground. */
export function Mark({ children }: { children: ReactNode }) {
    return <mark className="rounded-xs bg-accent/20 text-foreground">{children}</mark>
}
