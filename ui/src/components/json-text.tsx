import { Mark } from '@/components/marked-text'
import type { JsonKind, JsonToken } from '@/lib/json-lines'

/**
 * Tokens of agent output (`src/lib/json-lines.ts`), the JSON in them colored by what each piece is, the rest as plain
 * text, and a token a search found (`markedTokens`, `src/lib/search.ts`) marked. Everything is React text, never
 * HTML. Goes inside a `pre` that sets the font and wrapping.
 */
export function JsonTokens({ tokens }: { tokens: readonly (JsonToken & { mark?: boolean })[] }) {
    return tokens.map((token, i) => {
        const text =
            token.kind === 'text' ? (
                token.text
            ) : (
                <span key={i} className={TOKEN_CLASS[token.kind]}>
                    {token.text}
                </span>
            )
        return token.mark === true ? <Mark key={i}>{text}</Mark> : text
    })
}

// Anything that is not JSON stays the `pre`'s own color.
const TOKEN_CLASS: Record<Exclude<JsonKind, 'text'>, string> = {
    key: 'text-syntax-key',
    string: 'text-syntax-string',
    number: 'text-syntax-number',
    literal: 'text-syntax-literal',
    punct: 'text-muted-foreground',
}
