import { Fragment, useState } from 'react'

import { LinkedText } from '@/components/linked-text'
import { MoreLines } from '@/components/more-lines'
import { PullRequestLink } from '@/components/pull-request-link'
import { RunLink } from '@/components/run-link'
import { splitLinks } from '@/lib/links'
import type { Piece } from '@/lib/links'
import { isPullRequest, pullRequestLabel } from '@/lib/pull-request-label'
import { splitRunRefs } from '@/lib/refs'
import { clamp, codeSpans, parse } from '@/lib/rich-text'
import type { Block, Inline, Line } from '@/lib/rich-text'
import { cn } from '@/lib/utils'

/** How many lines a summary or a rationale shows in a list's row before its toggle. */
export const SUMMARY_LINES = 4

// Written out so Tailwind finds them.
const DEPTH: Record<number, string> = { 0: '', 1: 'ml-4', 2: 'ml-8', 3: 'ml-12' }

/**
 * Agent-written text laid out as it was written: line breaks, lists, headings, and code (`src/lib/rich-text.ts`). It is
 * untrusted, so every piece is React text, never HTML; a URL outside code is a link to itself (`LinkedText`, D113).
 * With `lines`, text longer than that shows its first lines and a toggle for the rest; a long line counts as the lines
 * it wraps to, so one long paragraph folds too. With `prose`, a paragraph's or an item's lines join with a space, as
 * Markdown's soft breaks do, for a file wrapped at a column (a persona) rather than written a line a thought. With
 * `pullRequests`, a GitHub PR's address is its `PullRequestLink`, as `LinkedText` names it. With `raised`, on a
 * surface already raised (a conversation's bubble), code sits on the canvas's color so it still stands apart.
 */
export function RichText({
    text,
    lines,
    prose = false,
    pullRequests = false,
    raised = false,
    className,
}: {
    text: string
    lines?: number
    prose?: boolean
    pullRequests?: boolean
    raised?: boolean
    className?: string
}) {
    const [open, setOpen] = useState(false)
    const blocks = parse(text)
    const cut = lines === undefined ? { blocks, hidden: 0 } : clamp(blocks, lines)
    const shown = open ? blocks : cut.blocks
    return (
        <div className={cn('flex min-w-0 flex-col gap-1.5 text-sm wrap-break-word', className)}>
            {shown.map((block, i) => (
                <BlockView key={i} block={block} prose={prose} look={{ pullRequests, raised }} />
            ))}
            {cut.hidden > 0 && <MoreLines hidden={cut.hidden} open={open} onToggle={() => setOpen(!open)} />}
        </div>
    )
}

/**
 * A line the harness wrote, an attention item's detail, with its `code` spans set as code and nothing else read: the
 * rest stays text, its URLs and the runs it names (`run:40`) linked unless `links` is false, as inside an element that
 * is already a link. A GitHub PR's address is named as the PR is anywhere (`acme/web#88`): a `PullRequestLink`, or its
 * name alone without links.
 */
export function InlineCode({ text, links = true }: { text: string; links?: boolean }) {
    return codeSpans(text).map((piece, i) =>
        piece.kind === 'code' ? (
            <Code key={i} text={piece.text} />
        ) : (
            <Fragment key={i}>
                {splitLinks(piece.text).map((part, j) => (
                    <HarnessText key={j} part={part} links={links} />
                ))}
            </Fragment>
        ),
    )
}

function HarnessText({ part, links }: { part: Piece; links: boolean }) {
    if (part.href === undefined) {
        if (!links) {
            return part.text
        }
        return splitRunRefs(part.text).map((piece, i) =>
            piece.run === undefined ? piece.text : <RunLink key={i} id={piece.run} />,
        )
    }
    if (isPullRequest(part.href)) {
        return links ? <PullRequestLink url={part.href} /> : pullRequestLabel(part.href)
    }
    return links ? <LinkedText text={part.text} /> : part.text
}

// How a piece is drawn where the text sits: its PRs named, and its code on the canvas when the surface is raised.
interface Look {
    pullRequests: boolean
    raised: boolean
}

function BlockView({ block, prose, look }: { block: Block; prose: boolean; look: Look }) {
    switch (block.kind) {
        case 'paragraph': {
            return (
                <p>
                    {block.lines.map((line, i) => (
                        <Fragment key={i}>
                            {i > 0 && (prose ? ' ' : <br />)}
                            <LineView line={line} look={look} />
                        </Fragment>
                    ))}
                </p>
            )
        }
        case 'heading': {
            return (
                <p className="font-medium">
                    <LineView line={block.line} look={look} />
                </p>
            )
        }
        case 'list': {
            const items = block.items.map((item, i) => (
                <li key={i} className={DEPTH[item.depth]}>
                    {item.lines.map((line, j) => (
                        <Fragment key={j}>
                            {j > 0 && (prose ? ' ' : <br />)}
                            <LineView line={line} look={look} />
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
                <pre
                    className={cn(
                        'overflow-x-auto rounded-sm border px-2 py-1.5 font-mono text-xs',
                        look.raised ? 'bg-background' : 'bg-surface-raised',
                    )}
                >
                    {block.lines.join('\n')}
                </pre>
            )
        }
    }
}

function LineView({ line, look }: { line: Line; look: Look }) {
    return line.map((piece, i) => <InlineView key={i} piece={piece} look={look} />)
}

function InlineView({ piece, look }: { piece: Inline; look: Look }) {
    switch (piece.kind) {
        case 'text': {
            return <LinkedText text={piece.text} pullRequests={look.pullRequests} />
        }
        case 'strong': {
            return (
                <strong className="font-semibold">
                    <LinkedText text={piece.text} pullRequests={look.pullRequests} />
                </strong>
            )
        }
        case 'code': {
            return <Code text={piece.text} raised={look.raised} />
        }
    }
}

function Code({ text, raised = false }: { text: string; raised?: boolean }) {
    return (
        <code className={cn('rounded-sm px-1 py-px font-mono text-xs', raised ? 'bg-background' : 'bg-surface-raised')}>
            {text}
        </code>
    )
}
