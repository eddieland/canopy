import { Fragment, useState } from 'react'

import { LinkedText } from '@/components/linked-text'
import { clamp, parse } from '@/lib/rich-text'
import type { Block, Inline, Line } from '@/lib/rich-text'
import { cn } from '@/lib/utils'

/** How many lines a summary or a rationale shows in a list's row before its toggle. */
export const SUMMARY_LINES = 4

// Written out so Tailwind finds them.
const DEPTH: Record<number, string> = { 0: '', 1: 'ml-4', 2: 'ml-8', 3: 'ml-12' }

/**
 * Agent-written text laid out as it was written: line breaks, lists, headings, and code (`src/lib/rich-text.ts`). It is
 * untrusted, so every piece is React text, never HTML; a URL outside code is a link to itself (`LinkedText`, D113).
 * With `lines`, text longer than that shows its first lines and a toggle for the rest.
 */
export function RichText({ text, lines, className }: { text: string; lines?: number; className?: string }) {
    const [open, setOpen] = useState(false)
    const blocks = parse(text)
    const cut = lines === undefined ? { blocks, hidden: 0 } : clamp(blocks, lines)
    const shown = open ? blocks : cut.blocks
    return (
        <div className={cn('flex min-w-0 flex-col gap-1.5 text-sm wrap-break-word', className)}>
            {shown.map((block, i) => (
                <BlockView key={i} block={block} />
            ))}
            {cut.hidden > 0 && (
                <button
                    type="button"
                    aria-expanded={open}
                    onClick={() => setOpen(!open)}
                    className={cn(
                        'self-start rounded-sm font-mono text-xs text-accent underline-offset-4 outline-none',
                        'hover:underline focus-visible:ring-3 focus-visible:ring-ring/50',
                    )}
                >
                    {open ? 'show less' : `show ${cut.hidden} more ${cut.hidden === 1 ? 'line' : 'lines'}`}
                </button>
            )}
        </div>
    )
}

function BlockView({ block }: { block: Block }) {
    switch (block.kind) {
        case 'paragraph': {
            return (
                <p>
                    {block.lines.map((line, i) => (
                        <Fragment key={i}>
                            {i > 0 && <br />}
                            <LineView line={line} />
                        </Fragment>
                    ))}
                </p>
            )
        }
        case 'heading': {
            return (
                <p className="font-medium">
                    <LineView line={block.line} />
                </p>
            )
        }
        case 'list': {
            const items = block.items.map((item, i) => (
                <li key={i} className={DEPTH[item.depth]}>
                    {item.lines.map((line, j) => (
                        <Fragment key={j}>
                            {j > 0 && <br />}
                            <LineView line={line} />
                        </Fragment>
                    ))}
                </li>
            ))
            const list = 'flex flex-col gap-0.5 pl-5 marker:text-muted-foreground'
            return block.ordered ? (
                <ol start={block.start} className={cn(list, 'list-decimal')}>
                    {items}
                </ol>
            ) : (
                <ul className={cn(list, 'list-disc')}>{items}</ul>
            )
        }
        case 'code': {
            return (
                <pre className="overflow-x-auto rounded-sm border bg-surface-raised px-2 py-1.5 font-mono text-xs">
                    {block.lines.join('\n')}
                </pre>
            )
        }
    }
}

function LineView({ line }: { line: Line }) {
    return line.map((piece, i) => <InlineView key={i} piece={piece} />)
}

function InlineView({ piece }: { piece: Inline }) {
    switch (piece.kind) {
        case 'text': {
            return <LinkedText text={piece.text} />
        }
        case 'strong': {
            return (
                <strong className="font-semibold">
                    <LinkedText text={piece.text} />
                </strong>
            )
        }
        case 'code': {
            return <code className="rounded-sm bg-surface-raised px-1 py-px font-mono text-[0.85em]">{piece.text}</code>
        }
    }
}
