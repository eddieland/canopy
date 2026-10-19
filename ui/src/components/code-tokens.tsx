import type { CodeKind, CodeToken } from '@/lib/highlight'

// A piece of code's color by what it is (ui/DESIGN.md, "A review"): the syntax tokens agent output's JSON wears, and
// comments muted. Anything else stays the line's own color.
const CODE_CLASS: Record<Exclude<CodeKind, 'text'>, string> = {
    keyword: 'text-syntax-literal',
    string: 'text-syntax-string',
    constant: 'text-syntax-number',
    function: 'text-syntax-key',
    comment: 'text-muted-foreground',
}

/** A line of code as its highlighted tokens (`src/lib/highlight.ts`), each colored by what it is, as React text. */
export function CodeTokens({ tokens }: { tokens: readonly CodeToken[] }) {
    // A line's tokens never reorder, so their index is their key.
    return tokens.map((token, i) =>
        token.kind === 'text' ? (
            token.text
        ) : (
            <span key={i} className={CODE_CLASS[token.kind]}>
                {token.text}
            </span>
        ),
    )
}
