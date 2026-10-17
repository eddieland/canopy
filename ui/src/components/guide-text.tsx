import { Link } from '@tanstack/react-router'
import { Fragment } from 'react'

import { anchor, plainText } from '@/lib/guide'
import type { GuidePiece } from '@/lib/guide'
import type { Block, Line } from '@/lib/rich-text'
import { cn } from '@/lib/utils'

// Written out so Tailwind finds them.
const DEPTH: Record<number, string> = { 0: '', 1: 'ml-4', 2: 'ml-8', 3: 'ml-12' }
const LINK = 'text-accent underline underline-offset-4 hover:decoration-2'

/**
 * A page of the guide laid out (`src/lib/guide.ts`): headings, each with its anchor as its id, paragraphs, lists, code,
 * and links. Its lines wrap as prose does, so a paragraph written across lines reads as one. Every piece is a React
 * element, never HTML.
 */
export function GuideText({ blocks }: { blocks: Block<GuidePiece>[] }) {
    return (
        <div className="flex max-w-3xl min-w-0 flex-col gap-3 text-sm/6 wrap-break-word">
            {blocks.map((block, i) => (
                <BlockView key={i} block={block} />
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

function BlockView({ block }: { block: Block<GuidePiece> }) {
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
            // A page's own title is its header's h1, so its body starts at h2.
            return block.level <= 2 ? (
                <h2 id={id} className="mt-3 scroll-mt-6 text-base font-semibold tracking-tight first:mt-0">
                    <LineView line={block.line} />
                </h2>
            ) : (
                <h3 id={id} className="mt-1 scroll-mt-6 font-medium">
                    <LineView line={block.line} />
                </h3>
            )
        }
        case 'list': {
            const items = block.items.map((item, i) => (
                <li key={i} className={DEPTH[item.depth]}>
                    <GuideLines lines={item.lines} />
                </li>
            ))
            const list = 'flex flex-col gap-1 pl-5 marker:text-muted-foreground'
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
                <pre className="overflow-x-auto rounded-sm border bg-surface-raised px-3 py-2 font-mono text-xs">
                    {block.lines.join('\n')}
                </pre>
            )
        }
    }
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
        case 'code': {
            return <code className="rounded-sm bg-surface-raised px-1 py-px font-mono text-xs">{piece.text}</code>
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
