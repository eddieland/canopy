import { Link } from '@tanstack/react-router'
import { Fragment } from 'react'

import { Code } from '@/components/code'
import { CodeTokens } from '@/components/code-tokens'
import { Skeleton } from '@/components/ui/skeleton'
import { useDiagram } from '@/hooks/use-diagram'
import { useHighlightLines } from '@/hooks/use-highlight'
import { DIAGRAM_FENCE, anchor, diagramTitle, plainText } from '@/lib/guide'
import type { GuidePiece } from '@/lib/guide'
import type { CodeToken } from '@/lib/highlight'
import { fenceLanguage } from '@/lib/languages'
import { ALIGN } from '@/lib/rich-text'
import type { Align, Block, Line } from '@/lib/rich-text'
import { cn } from '@/lib/utils'
import { usePalettes } from '@/theme/palette'
import { useTheme } from '@/theme/use-theme'

// Written out so Tailwind finds them.
const DEPTH: Record<number, string> = { 0: '', 1: 'ml-4', 2: 'ml-8', 3: 'ml-12' }
const LINK = 'text-accent underline underline-offset-4 hover:decoration-2'

/**
 * A page of the guide laid out as a documentation site's article (`src/lib/guide.ts`), in a document's type as a plan
 * is (`document-text` in `src/index.css`): headings, each with its anchor as its id and a `#` link to itself on hover,
 * paragraphs, lists, quotes, rules, tables, code, and links. Its lines wrap as prose does, so a paragraph written
 * across lines reads as one. Every piece is a React element, never HTML.
 */
export function GuideText({ blocks, page }: { blocks: Block<GuidePiece>[]; page: string }) {
    return (
        <div className="flex min-w-0 flex-col gap-4 document-text wrap-break-word">
            {blocks.map((block, i) => (
                <BlockView key={i} block={block} page={page} />
            ))}
        </div>
    )
}

/** A line of the guide, its soft line breaks as spaces: a page's lead, under its header and in the guide's list. */
export function GuideLines({ lines }: { lines: Line<GuidePiece>[] }) {
    return lines.map((line, i) => (
        <Fragment key={i}>
            {i > 0 && ' '}
            <LineView line={line} />
        </Fragment>
    ))
}

function BlockView({ block, page }: { block: Block<GuidePiece>; page: string }) {
    switch (block.kind) {
        case 'paragraph': {
            return (
                <p>
                    <GuideLines lines={block.lines} />
                </p>
            )
        }
        case 'heading': {
            const id = anchor(plainText(block.line))
            const self = (
                <Link
                    to="/guide/$page"
                    params={{ page }}
                    hash={id}
                    aria-label={`Link to ${plainText(block.line)}`}
                    className={cn(
                        'ml-2 text-muted-foreground no-underline opacity-0',
                        'group-hover:opacity-100 focus:opacity-100',
                    )}
                >
                    #
                </Link>
            )
            // A page's own title is its header's h1, so its body starts at h2: a section, under a rule.
            return block.level <= 2 ? (
                <h2
                    id={id}
                    className={cn(
                        'group mt-4 scroll-mt-6 border-t pt-6 document-section',
                        'first:mt-0 first:border-t-0 first:pt-0',
                    )}
                >
                    <LineView line={block.line} />
                    {self}
                </h2>
            ) : (
                <h3 id={id} className="group mt-2 scroll-mt-6 document-subsection">
                    <LineView line={block.line} />
                    {self}
                </h3>
            )
        }
        case 'list': {
            const items = block.items.map((item, i) => (
                <li key={i} className={DEPTH[item.depth]}>
                    <GuideLines lines={item.lines} />
                </li>
            ))
            const list = 'flex flex-col gap-1.5 pl-6 marker:text-muted-foreground'
            return block.ordered ? (
                <ol start={block.start} className={cn(list, 'list-decimal')}>
                    {items}
                </ol>
            ) : (
                <ul className={cn(list, 'list-disc')}>{items}</ul>
            )
        }
        case 'quote': {
            return (
                <blockquote className="flex flex-col gap-4 border-l-2 pl-4 text-muted-foreground">
                    {block.blocks.map((inner, i) => (
                        <BlockView key={i} block={inner} page={page} />
                    ))}
                </blockquote>
            )
        }
        case 'rule': {
            return <hr />
        }
        case 'table': {
            return (
                <div className="overflow-x-auto">
                    <table className="border-collapse text-left">
                        <thead>
                            <tr className="border-b">
                                {block.head.map((line, i) => (
                                    <th key={i} scope="col" className={cn(cellClass(block.align[i]), 'font-semibold')}>
                                        <LineView line={line} />
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {block.rows.map((row, i) => (
                                <tr key={i} className="border-b last:border-b-0">
                                    {row.map((line, j) => (
                                        <td key={j} className={cellClass(block.align[j])}>
                                            <LineView line={line} />
                                        </td>
                                    ))}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )
        }
        case 'code': {
            return block.lang === DIAGRAM_FENCE ? (
                <Diagram lines={block.lines} />
            ) : (
                <CodeBlock lines={block.lines} lang={block.lang} />
            )
        }
    }
}

// A table cell's class, set as its column's delimiter row asks.
function cellClass(align: Align): string {
    return cn('px-3 py-2 align-top first:pl-0 last:pr-0', align && ALIGN[align])
}

// A Mermaid fence, drawn as its diagram: an image named by its `accTitle`, drawn again when the theme or a palette
// changes. A placeholder holds its place while mermaid loads; a diagram it cannot draw shows its code and why.
function Diagram({ lines }: { lines: string[] }) {
    const { resolved } = useTheme()
    const { light, dark } = usePalettes()
    const drawn = useDiagram(lines.join('\n'), `${resolved} ${light} ${dark}`)
    if (drawn === undefined) {
        return <Skeleton className="h-64 w-full rounded-md" />
    }
    if ('error' in drawn) {
        return (
            <figure className="flex flex-col gap-2">
                <CodeBlock lines={lines} lang={DIAGRAM_FENCE} />
                <figcaption className="text-sm text-muted-foreground">Not drawn: {drawn.error}.</figcaption>
            </figure>
        )
    }
    return (
        <figure className="overflow-x-auto rounded-md border px-4 py-5">
            <img
                src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(drawn.svg)}`}
                alt={diagramTitle(lines) ?? 'A diagram'}
                className="mx-auto h-auto max-w-full"
            />
        </figure>
    )
}

// A code block, colored by the language its fence names once that grammar has read it, plain text until then.
function CodeBlock({ lines, lang }: { lines: string[]; lang: string | undefined }) {
    const tokens = useHighlightLines(lang === undefined ? undefined : fenceLanguage(lang), lines)
    return (
        <pre
            className="overflow-x-auto rounded-md border bg-surface-raised px-4 py-3 font-mono text-sm/6"
            data-highlighted={tokens !== undefined || undefined}
        >
            {tokens === undefined ? lines.join('\n') : <HighlightedLines lines={lines} tokens={tokens} />}
        </pre>
    )
}

// A code block's lines, each as its tokens, or as written when Shiki could not account for it.
function HighlightedLines({ lines, tokens }: { lines: string[]; tokens: (CodeToken[] | undefined)[] }) {
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

function LineView({ line }: { line: Line<GuidePiece> }) {
    return line.map((piece, i) => <PieceView key={i} piece={piece} />)
}

function PieceView({ piece }: { piece: GuidePiece }) {
    switch (piece.kind) {
        case 'text': {
            return piece.text
        }
        case 'strong': {
            return <strong className="font-semibold">{piece.text}</strong>
        }
        case 'em': {
            return <em className="italic">{piece.text}</em>
        }
        case 'del': {
            return <del className="line-through">{piece.text}</del>
        }
        case 'code': {
            return <Code>{piece.text}</Code>
        }
        case 'link': {
            return <GuideLink piece={piece} />
        }
    }
}

function GuideLink({ piece }: { piece: GuidePiece & { kind: 'link' } }) {
    const { target, text } = piece
    switch (target.kind) {
        case 'page': {
            return (
                <Link to="/guide/$page" params={{ page: target.page }} hash={target.hash} className={LINK}>
                    {text}
                </Link>
            )
        }
        case 'section': {
            return (
                <Link to={target.to} className={LINK}>
                    {text}
                </Link>
            )
        }
        case 'web': {
            return (
                <a href={target.href} target="_blank" rel="noreferrer noopener" className={LINK}>
                    {text}
                </a>
            )
        }
    }
}
