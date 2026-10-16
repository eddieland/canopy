import { ChevronsUpDown } from 'lucide-react'
import { Fragment, useState } from 'react'
import type { ReactNode } from 'react'

import type { DiffFile, DiffLine, ReviewDiff } from '@/api/types'
import { useDismissReviewFinding } from '@/components/dismiss-finding'
import { Panel, PanelHeader } from '@/components/panel'
import { RichText } from '@/components/rich-text'
import { Chip } from '@/components/status'
import { Button } from '@/components/ui/button'
import { useHighlight } from '@/hooks/use-highlight'
import type { CodeKind, CodeToken } from '@/lib/highlight'
import { foldedText, foldLabel, lineCount, nextStep, pieces, reveal, shownAtFirst } from '@/lib/review-folds'
import type { Piece, Span } from '@/lib/review-folds'
import { findingAnchor, SEVERITY_TONE } from '@/lib/reviews'
import type { Numbered, Placed } from '@/lib/reviews'
import { cn } from '@/lib/utils'

// Full class names, written out, so Tailwind finds them: a line's tint and its +/- mark.
const LINE_TINT: Record<DiffLine['kind'], string> = { add: 'bg-diff-add/12', del: 'bg-diff-del/12', ctx: '' }
const LINE_MARK: Record<DiffLine['kind'], string> = { add: 'text-diff-add', del: 'text-diff-del', ctx: '' }
const MARK: Record<DiffLine['kind'], string> = { add: '+', del: '-', ctx: ' ' }
// A piece of code's color by what it is (ui/DESIGN.md, "A review"): the syntax tokens agent output's JSON wears, and
// comments muted. Anything else stays the line's own color.
const CODE_CLASS: Record<Exclude<CodeKind, 'text'>, string> = {
    keyword: 'text-syntax-literal',
    string: 'text-syntax-string',
    constant: 'text-syntax-number',
    function: 'text-syntax-key',
    comment: 'text-muted-foreground',
}

/**
 * The reviewed commit's diff, a panel per file, with each finding's card under the line it names, or under the file's
 * header when the diff does not show its line. The diff is the PR's own text: every line is React text, its code
 * colored once its language's grammar has read it (`useHighlight`). A diff longer than the page's budget folds what it
 * does not draw at first (`DIFF_BUDGET`), and says so above its first file.
 */
export function ReviewDiffPanels({ run, diff, placed }: { run: number; diff: ReviewDiff; placed: Placed }) {
    const first = shownAtFirst(diff.files, placed.lines)
    const total = diff.files.reduce((sum, file) => sum + lineCount(file), 0)
    const drawn = first.flat().reduce((sum, span) => sum + span.to - span.from, 0)
    return (
        <>
            {drawn < total && (
                <p className="font-mono text-xs text-muted-foreground" data-testid="diff-folded">
                    {foldedText(drawn, total)}
                </p>
            )}
            {diff.files.map((file, i) => (
                <FilePanel
                    key={`${i}:${file.path}`}
                    run={run}
                    file={file}
                    first={first[i] ?? []}
                    onLine={placed.lines.get(i)}
                    onFile={placed.files.get(i) ?? []}
                />
            ))}
            {diff.truncated && (
                <p className="font-mono text-xs text-muted-foreground">
                    The diff is longer than the page shows; the rest is left out.
                </p>
            )}
        </>
    )
}

function FilePanel({
    run,
    file,
    first,
    onLine,
    onFile,
}: {
    run: number
    file: DiffFile
    first: Span[]
    onLine: Map<number, Numbered[]> | undefined
    onFile: Numbered[]
}) {
    // The lines the operator opened, drawn with those the page draws at first, which follow the review as it changes:
    // a running review's findings arrive when it ends, and each brings its lines into view, folded or not.
    const [opened, setOpened] = useState<Span[]>([])
    const shown = opened.reduce((spans, span) => reveal(spans, span), first)
    const highlighted = useHighlight(file)
    const show = (span: Span) => setOpened((was) => reveal(was, nextStep(span)))
    const rows = pieces(file, shown).flatMap((piece) => pieceRows(piece, { run, file, highlighted, onLine, show }))
    return (
        <Panel data-testid="diff-file">
            <PanelHeader label="File">
                <span className="min-w-0 flex-1 truncate font-mono text-xs" title={file.path}>
                    {file.old_path !== null && <span className="text-muted-foreground">{file.old_path} → </span>}
                    {file.path}
                </span>
                {file.binary && <Chip>binary</Chip>}
            </PanelHeader>
            {onFile.length > 0 && (
                <div className="flex flex-col gap-2 border-b p-3">
                    {onFile.map((f) => (
                        <FindingCard key={f.n} run={run} numbered={f} />
                    ))}
                </div>
            )}
            {rows.length > 0 && (
                <div className="overflow-x-auto">
                    <table className="w-full border-collapse font-mono text-xs">
                        <tbody>{rows}</tbody>
                    </table>
                </div>
            )}
        </Panel>
    )
}

/**
 * The table rows of one piece of a file: a hunk's header, its lines with the cards of the findings on them, or a fold.
 * Keyed by where they are in the file, so the rows drawn already keep their keys when a fold opens above them.
 */
function pieceRows(
    piece: Piece,
    {
        run,
        file,
        highlighted,
        onLine,
        show,
    }: {
        run: number
        file: DiffFile
        highlighted: (CodeToken[] | undefined)[][] | undefined
        onLine: Map<number, Numbered[]> | undefined
        show: (span: Span) => void
    },
): ReactNode[] {
    switch (piece.kind) {
        case 'hunk': {
            const header = file.hunks[piece.hunk]?.header
            return [
                <tr key={`hunk-${piece.hunk}`} className="bg-surface-raised text-muted-foreground">
                    <td colSpan={4} className="px-3 py-1 whitespace-pre">
                        {header ? `@@ ${header}` : '@@'}
                    </td>
                </tr>,
            ]
        }
        case 'lines': {
            const lines = file.hunks[piece.hunk]?.lines.slice(piece.from, piece.to) ?? []
            return lines.map((line, k) => {
                const cards = line.new !== null && line.kind !== 'del' ? onLine?.get(line.new) : undefined
                return (
                    <Fragment key={`line-${piece.hunk}-${piece.from + k}`}>
                        <Line line={line} tokens={highlighted?.[piece.hunk]?.[piece.from + k]} />
                        {cards !== undefined && (
                            <tr>
                                <td colSpan={4} className="border-y bg-surface p-0">
                                    <InView className="flex flex-col gap-2 px-3 py-2 font-sans">
                                        {cards.map((f) => (
                                            <FindingCard key={f.n} run={run} numbered={f} />
                                        ))}
                                    </InView>
                                </td>
                            </tr>
                        )}
                    </Fragment>
                )
            })
        }
        case 'fold': {
            return [<Fold key={`fold-${piece.span.from}`} span={piece.span} onShow={() => show(piece.span)} />]
        }
    }
}

/**
 * What sits in a row across the whole table, kept to the panel's width and its left edge while the lines scroll
 * sideways: a long line would otherwise stretch a finding's card, and its text, past the panel's edge.
 */
function InView({ className, children }: { className?: string; children: ReactNode }) {
    return <div className={cn('sticky left-0 w-[100cqw]', className)}>{children}</div>
}

/** A run of lines the page does not draw yet, and a button to draw the next of them. */
function Fold({ span, onShow }: { span: Span; onShow: () => void }) {
    return (
        <tr className="border-y bg-surface-raised/50" data-testid="diff-fold">
            <td colSpan={4} className="px-1 py-0.5">
                {/* At the panel's left edge, as a card is, while the lines scroll sideways. */}
                <Button variant="ghost" size="xs" onClick={onShow} className="sticky left-1">
                    <ChevronsUpDown />
                    {foldLabel(span)}
                </Button>
            </td>
        </tr>
    )
}

function Line({ line, tokens }: { line: DiffLine; tokens: CodeToken[] | undefined }) {
    return (
        <tr className={LINE_TINT[line.kind]} data-kind={line.kind}>
            <td className="w-12 px-2 text-right text-muted-foreground tabular-nums select-none">{line.old ?? ''}</td>
            <td className="w-12 px-2 text-right text-muted-foreground tabular-nums select-none">{line.new ?? ''}</td>
            <td aria-hidden className={cn('w-4 select-none', LINE_MARK[line.kind])}>
                {MARK[line.kind]}
            </td>
            <td className="pr-3 whitespace-pre" data-highlighted={tokens !== undefined || undefined}>
                {tokens === undefined ? line.text : <Code tokens={tokens} />}
            </td>
        </tr>
    )
}

function Code({ tokens }: { tokens: CodeToken[] }) {
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

/**
 * One finding: its number and severity, its title and where, and its detail as rich text, as an agent wrote it. A small
 * button at the end of its head line dismisses it, so no worker or tick acts on it; a dismissed one says so.
 */
export function FindingCard({ run, numbered, className }: { run: number; numbered: Numbered; className?: string }) {
    const { n, finding } = numbered
    const { button, notice } = useDismissReviewFinding(run, n, finding.dismissed)
    return (
        <article
            id={findingAnchor(n)}
            className={cn('scroll-mt-16 rounded-md border bg-surface-raised p-3 text-sm', className)}
            data-testid="finding"
            data-dismissed={finding.dismissed || undefined}
        >
            <header className="flex flex-wrap items-center gap-2">
                <span className="readout text-xs text-muted-foreground">{n}</span>
                <Chip tone={SEVERITY_TONE[finding.severity]}>{finding.severity}</Chip>
                <span className={cn('font-medium', finding.dismissed && 'text-muted-foreground')}>{finding.title}</span>
                {finding.location && (
                    <span className="font-mono text-xs break-all text-muted-foreground">{finding.location}</span>
                )}
                {finding.dismissed && <Chip>dismissed</Chip>}
                <span className="ml-auto">{button}</span>
            </header>
            {finding.detail && <RichText text={finding.detail} className="mt-1.5 text-muted-foreground" />}
            {notice}
        </article>
    )
}
