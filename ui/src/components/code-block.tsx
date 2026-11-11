import { Fragment } from 'react'

import { BlockActions, CodeActions } from '@/components/block-actions'
import { CodeTokens } from '@/components/code-tokens'
import { useHighlightLines } from '@/hooks/use-highlight'
import type { CodeToken } from '@/lib/highlight'
import { fenceLanguage } from '@/lib/languages'
import { cn } from '@/lib/utils'

/**
 * A fenced code block, colored by the language its fence names (`lang`, by Shiki's name or a file's extension;
 * `fenceLanguage`) once that grammar has read it: plain text until then, and for good in a language canopy does not
 * highlight or with no fence language at all, the same characters in the same place. Its tokens are React text, never
 * HTML. `className` sets the block's box, which the guide and rich text draw each their own way. Its code is copied
 * from its corner (`CodeActions`), unless `copy` is false, where what holds it has actions of its own.
 */
export function CodeBlock({
    lines,
    lang,
    className,
    copy = true,
}: {
    /** The block's lines, as the fence holds them. */
    lines: readonly string[]
    /** The language its fence names, if any. */
    lang: string | undefined
    /** Classes for its box. */
    className?: string
    /** Whether it offers its code copied, in its corner. */
    copy?: boolean
}) {
    const tokens = useHighlightLines(lang === undefined ? undefined : fenceLanguage(lang), lines)
    const block = (
        <pre
            className={cn('overflow-x-auto font-mono', className)}
            data-highlighted={tokens !== undefined || undefined}
        >
            {tokens === undefined ? lines.join('\n') : <HighlightedLines lines={lines} tokens={tokens} />}
        </pre>
    )
    if (!copy) {
        return block
    }
    return (
        <div className="group/block relative min-w-0">
            {block}
            <BlockActions>
                <CodeActions text={lines.join('\n')} />
            </BlockActions>
        </div>
    )
}

// A code block's lines, each as its tokens, or as written when Shiki could not account for it.
function HighlightedLines({ lines, tokens }: { lines: readonly string[]; tokens: (CodeToken[] | undefined)[] }) {
    return lines.map((line, i) => {
        const lineTokens = tokens[i]
        return (
            <Fragment key={i}>
                {i > 0 && '\n'}
                {lineTokens === undefined ? line : <CodeTokens tokens={lineTokens} />}
            </Fragment>
        )
    })
}
