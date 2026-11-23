import { ChevronDown, ListFilter, Plus } from 'lucide-react'
import { Fragment, useState } from 'react'
import type { ReactNode } from 'react'

import type { DiffFile, DiffLine, ReviewDiff, ReviewDraft } from '@/api/types'
import { CodeTokens } from '@/components/code-tokens'
import { Disclosure } from '@/components/disclosure'
import { dismissedLabel, useDismissReviewFinding } from '@/components/dismiss-finding'
import { FoldButton } from '@/components/fold-button'
import { Panel, PanelHeader } from '@/components/panel'
import { DraftCommentCard, NewCommentCard, ReviewPointCard } from '@/components/review-draft'
import { RichText } from '@/components/rich-text'
import { Chip } from '@/components/status'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useHighlight } from '@/hooks/use-highlight'
import { changedWords, fileLines, hunkRange, lineParts } from '@/lib/diff-words'
import type { Changed } from '@/lib/diff-words'
import { fileType, fileTypes, fileTypesLabel, hiddenFilesText } from '@/lib/file-types'
import type { FileType } from '@/lib/file-types'
import type { CodeToken } from '@/lib/highlight'
import { editable, placeReviewCards } from '@/lib/review-drafts'
import type { Adding, ReviewCard } from '@/lib/review-drafts'
import {
    fileFoldedText,
    foldedText,
    foldLabel,
    lineCount,
    nextStep,
    pieces,
    reveal,
    shownAtFirst,
} from '@/lib/review-folds'
import type { Piece, Span } from '@/lib/review-folds'
import { findingAnchor, SEVERITY_TONE } from '@/lib/reviews'
import type { Numbered, Placed } from '@/lib/reviews'
import { linesText } from '@/lib/run-changes'
import { cn } from '@/lib/utils'

// Full class names, written out, so Tailwind finds them: a line's tint and its +/- mark.
const LINE_TINT: Record<DiffLine['kind'], string> = { add: 'bg-diff-add/12', del: 'bg-diff-del/12', ctx: '' }
const LINE_MARK: Record<DiffLine['kind'], string> = { add: 'text-diff-add', del: 'text-diff-del', ctx: '' }
const MARK: Record<DiffLine['kind'], string> = { add: '+', del: '-', ctx: ' ' }
// The words that changed within a line: a second layer of its tint, and plain `foreground`, since no code color reads
// at 4.5:1 on the two together (src/styles/tokens.test.ts).
const WORD: Record<DiffLine['kind'], string> = {
    add: 'rounded-xs bg-diff-add/25 text-foreground',
    del: 'rounded-xs bg-diff-del/25 text-foreground',
    ctx: '',
}

/** Which sides' line numbers a file's table has a column for: a file only added to has no old side to number. */
interface Sides {
    /** Whether any line has a number on the old side. */
    old: boolean
    /** Whether any line has a number on the new side. */
    new: boolean
}

/** A file of a diff the operator just asked to see, by following a link to a card on it, a new object each time. */
export interface Wanted {
    /** The file's index in the diff. */
    file: number
}

/**
 * The reviewed commit's diff, a panel per file, with each finding's card under the line it names, or under the file's
 * header when the diff does not show its line (`DiffPanels`). `wanted` is the file of the finding or comment whose link
 * the operator last followed. On a review with a draft (DESIGN §34), each finding's card is the point of the
 * operator's review it makes (`ReviewPointCard`), its comment included, and each comment the operator added has a card
 * on its line too, after the findings there; while the draft waits, the + beside a line's number opens a new comment's
 * form under it.
 */
export function ReviewDiffPanels({
    run,
    diff,
    placed,
    draft = null,
    wanted = null,
}: {
    run: number
    diff: ReviewDiff
    placed: Placed<Numbered>
    draft?: ReviewDraft | null
    wanted?: Wanted | null
}) {
    const [adding, setAdding] = useState<Adding | null>(null)
    const open = draft !== null && editable(draft)
    const cards = placeReviewCards(placed, draft?.comments ?? [], open ? adding : null)
    const add = (file: number, line: number) => {
        const path = diff.files[file]?.path
        if (path !== undefined) {
            setAdding({ file, path, line })
        }
    }
    const renderCard = (card: ReviewCard) => {
        switch (card.kind) {
            case 'finding': {
                const key = `finding-${card.numbered.n}`
                return draft === null ? (
                    <FindingCard key={key} run={run} numbered={card.numbered} />
                ) : (
                    <ReviewPointCard key={key} run={run} numbered={card.numbered} draft={draft} />
                )
            }
            case 'comment': {
                return (
                    draft !== null && (
                        <DraftCommentCard
                            key={`comment-${card.comment.number}`}
                            run={run}
                            comment={card.comment}
                            draft={draft}
                        />
                    )
                )
            }
            case 'new': {
                return <NewCommentCard key="new" run={run} adding={card.adding} onDone={() => setAdding(null)} />
            }
        }
    }
    return (
        <DiffPanels
            diff={diff}
            placed={cards}
            cards={draft === null ? ['finding', 'findings'] : ['note', 'notes']}
            wanted={wanted}
            renderCard={renderCard}
            onAdd={open ? add : undefined}
        />
    )
}

/**
 * A diff, a panel per file, with the card of each thing placed on it under the line it names, or under the file's
 * header when the diff does not show its line: a review's findings, a PR's threads. `renderCard` draws one, keyed, and
 * `cards` names them, one and many. The diff is the PR's own text: every line is React text, its code colored once its
 * language's grammar has read it (`useHighlight`). A diff longer than the page's budget folds what it does not draw at
 * first (`DIFF_BUDGET`), and says so above its first file. Above the files, a menu of their types hides the files of
 * those the operator unticks, every type ticked at first; and each file's panel folds away whole on its header's
 * disclosure. A `wanted` file, one the operator followed a link to a card on, comes back into view: its type ticked
 * and its panel open. Each new object shows it again, so following the same link twice works twice. With `onAdd`, each
 * line on the new side has a + beside its number, which `onAdd` hears with the file's index and the line. Each file's
 * title is a heading that names its path, at `level`: 3 where the diff sits under a panel of its own, as a run's Diff.
 */
export function DiffPanels<T>({
    diff,
    placed,
    cards,
    renderCard,
    wanted = null,
    onAdd,
    level = 2,
}: {
    diff: ReviewDiff
    placed: Placed<T>
    cards: readonly [string, string]
    renderCard: (item: T) => ReactNode
    wanted?: Wanted | null
    onAdd?: (file: number, line: number) => void
    level?: 2 | 3
}) {
    const first = shownAtFirst(diff.files, placed.lines)
    const total = diff.files.reduce((sum, file) => sum + lineCount(file), 0)
    const drawn = first.flat().reduce((sum, span) => sum + span.to - span.from, 0)
    const types = fileTypes(diff.files.map((file) => file.path))
    // Held here rather than in each file's panel, which the filter unmounts, so a file it hides keeps its fold, and the
    // lines opened in it, for when it comes back. Both are by the file's index.
    const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set())
    const [folded, setFolded] = useState<ReadonlySet<number>>(new Set())
    const [opened, setOpened] = useState<ReadonlyMap<number, Span[]>>(new Map())
    // A file just wanted is shown as the page draws it, before the router scrolls to the card on it.
    const [seen, setSeen] = useState(wanted)
    if (wanted !== seen) {
        setSeen(wanted)
        const path = wanted === null ? undefined : diff.files[wanted.file]?.path
        if (wanted !== null && path !== undefined) {
            setHidden((was) => without(was, fileType(path)))
            setFolded((was) => without(was, wanted.file))
        }
    }
    const hiddenFiles = diff.files.filter((file) => hidden.has(fileType(file.path))).length
    return (
        <>
            {diff.files.length > 0 && (
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <FileTypeFilter types={types} hidden={hidden} onHiddenChange={setHidden} />
                    {hiddenFiles > 0 && (
                        <span className="font-mono text-xs text-muted-foreground" data-testid="diff-hidden-files">
                            {hiddenFilesText(hiddenFiles)}
                        </span>
                    )}
                </div>
            )}
            {drawn < total && (
                <p className="font-mono text-xs text-muted-foreground" data-testid="diff-folded">
                    {foldedText(drawn, total)}
                </p>
            )}
            {diff.files.map(
                (file, i) =>
                    !hidden.has(fileType(file.path)) && (
                        <FilePanel
                            key={`${i}:${file.path}`}
                            file={file}
                            first={first[i] ?? []}
                            onLine={placed.lines.get(i)}
                            onFile={placed.files.get(i) ?? []}
                            cards={cards}
                            renderCard={renderCard}
                            opened={opened.get(i) ?? []}
                            onShow={(span) =>
                                setOpened((was) => new Map(was).set(i, reveal(was.get(i) ?? [], nextStep(span))))
                            }
                            open={!folded.has(i)}
                            onOpenChange={(open) => setFolded((was) => (open ? without(was, i) : new Set([...was, i])))}
                            onAdd={onAdd === undefined ? undefined : (line) => onAdd(i, line)}
                            level={level}
                        />
                    ),
            )}
            {diff.truncated && (
                <p className="font-mono text-xs text-muted-foreground">
                    The diff is longer than the page shows; the rest is left out.
                </p>
            )}
        </>
    )
}

function without<T>(set: ReadonlySet<T>, item: T): ReadonlySet<T> {
    if (!set.has(item)) {
        return set
    }
    const next = new Set(set)
    next.delete(item)
    return next
}

/**
 * The menu of the diff's file types, each with how many files are of it and a check while its files show. Picking one
 * flips it and leaves the menu open, so several flip in one go; `Show every type` ticks them all again.
 */
function FileTypeFilter({
    types,
    hidden,
    onHiddenChange,
}: {
    types: readonly FileType[]
    hidden: ReadonlySet<string>
    onHiddenChange: (hidden: ReadonlySet<string>) => void
}) {
    const shown = (type: string, on: boolean) => {
        onHiddenChange(on ? without(hidden, type) : new Set([...hidden, type]))
    }
    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <Button variant="outline" size="xs" data-testid="diff-file-types">
                    <ListFilter aria-hidden />
                    {fileTypesLabel(types, hidden)}
                    <ChevronDown aria-hidden />
                </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-44">
                {types.map(({ type, count }) => (
                    <DropdownMenuCheckboxItem
                        key={type}
                        checked={!hidden.has(type)}
                        onCheckedChange={(checked) => shown(type, checked)}
                        onSelect={(event) => event.preventDefault()}
                        aria-label={`${type}, ${count} ${count === 1 ? 'file' : 'files'}`}
                    >
                        <span className="font-mono text-xs">{type}</span>
                        <span className="ml-auto readout text-xs text-muted-foreground">{count}</span>
                    </DropdownMenuCheckboxItem>
                ))}
                {types.some(({ type }) => hidden.has(type)) && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem onSelect={() => onHiddenChange(new Set())}>Show every type</DropdownMenuItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

function FilePanel<T>({
    file,
    first,
    onLine,
    onFile,
    cards,
    renderCard,
    opened,
    onShow,
    open,
    onOpenChange,
    onAdd,
    level,
}: {
    file: DiffFile
    first: Span[]
    onLine: Map<number, T[]> | undefined
    onFile: T[]
    cards: readonly [string, string]
    renderCard: (item: T) => ReactNode
    opened: Span[]
    onShow: (span: Span) => void
    open: boolean
    onOpenChange: (open: boolean) => void
    onAdd: ((line: number) => void) | undefined
    level: 2 | 3
}) {
    // The lines the operator opened, drawn with those the page draws at first, which follow the review as it changes:
    // a running review's findings arrive when it ends, and each brings its lines into view, folded or not, as a thread
    // read again does.
    const shown = opened.reduce((spans, span) => reveal(spans, span), first)
    const highlighted = useHighlight(file)
    const changed = changedWords(file)
    const lines = file.hunks.flatMap((hunk) => hunk.lines)
    const sides: Sides = {
        old: lines.some((line) => typeof line.old === 'number'),
        new: lines.some((line) => typeof line.new === 'number'),
    }
    const rows = pieces(file, shown).flatMap((piece) =>
        pieceRows(piece, { file, highlighted, changed, sides, onLine, show: onShow, renderCard, add: onAdd }),
    )
    const count = onFile.length + [...(onLine?.values() ?? [])].reduce((sum, items) => sum + items.length, 0)
    const body = onFile.length > 0 || rows.length > 0
    const named = file.old_path === null ? file.path : `${file.old_path} → ${file.path}`
    // The file's name leads the eye, and is what a path too long for the header keeps.
    const slash = file.path.lastIndexOf('/') + 1
    const { added, removed } = fileLines(file)
    const [plus, minus] = linesText(added, removed)
    return (
        <Collapsible asChild open={open || !body} onOpenChange={onOpenChange}>
            <Panel data-testid="diff-file">
                {/* It stays in view while its lines scroll under it, so a long file never loses its name. */}
                <PanelHeader label="File" level={level} spoken={named} sticky>
                    {/* Its heading names it to a screen reader, which this line would say again. */}
                    <span aria-hidden className="flex min-w-0 flex-1 font-mono text-xs" title={named}>
                        <span className="truncate text-muted-foreground">
                            {file.old_path !== null && `${file.old_path} → `}
                            {file.path.slice(0, slash)}
                        </span>
                        <span className="shrink-0">{file.path.slice(slash)}</span>
                    </span>
                    {added + removed > 0 && (
                        <span className="readout text-xs whitespace-nowrap" data-testid="diff-file-lines">
                            <span className="text-diff-add">{plus}</span> <span className="text-diff-del">{minus}</span>
                        </span>
                    )}
                    {file.binary && <Chip>binary</Chip>}
                    {body && <Disclosure open={open} what="diff" of={file.path} />}
                </PanelHeader>
                <CollapsibleContent>
                    {onFile.length > 0 && (
                        <div className="flex flex-col gap-2 border-b p-3">{onFile.map((item) => renderCard(item))}</div>
                    )}
                    {rows.length > 0 && (
                        <div className="overflow-x-auto">
                            <table className="w-full border-collapse font-mono text-xs/4.5 tab-4">
                                <tbody>{rows}</tbody>
                            </table>
                        </div>
                    )}
                </CollapsibleContent>
                {!open && body && (
                    <p className="px-3 py-2 font-mono text-xs text-muted-foreground">
                        {fileFoldedText(lineCount(file), count, cards)}
                    </p>
                )}
            </Panel>
        </Collapsible>
    )
}

/**
 * The table rows of one piece of a file: a hunk's header, its lines with the cards placed on them, or a fold.
 * Keyed by where they are in the file, so the rows drawn already keep their keys when a fold opens above them.
 */
function pieceRows<T>(
    piece: Piece,
    {
        file,
        highlighted,
        changed,
        sides,
        onLine,
        show,
        renderCard,
        add,
    }: {
        file: DiffFile
        highlighted: (CodeToken[] | undefined)[][] | undefined
        changed: (Changed[] | undefined)[][]
        sides: Sides
        onLine: Map<number, T[]> | undefined
        show: (span: Span) => void
        renderCard: (item: T) => ReactNode
        add: ((line: number) => void) | undefined
    },
): ReactNode[] {
    // The mark and the code, and a column for each side numbered.
    const columns = 2 + Number(sides.old) + Number(sides.new)
    switch (piece.kind) {
        case 'hunk': {
            const hunk = file.hunks[piece.hunk]
            if (hunk === undefined) {
                return []
            }
            return [
                <tr key={`hunk-${piece.hunk}`} className="bg-surface-raised text-muted-foreground">
                    <td colSpan={columns} className="px-3 py-1 whitespace-pre">
                        {/* Git's own line, its ranges from the lines' numbers, kept at the panel's left edge. */}
                        <span className="sticky left-3">
                            @@ {hunkRange(hunk)} @@{hunk.header !== '' && ` ${hunk.header}`}
                        </span>
                    </td>
                </tr>,
            ]
        }
        case 'lines': {
            const lines = file.hunks[piece.hunk]?.lines.slice(piece.from, piece.to) ?? []
            return lines.map((line, k) => {
                const at = line.kind === 'del' ? null : line.new
                const cards = at === null ? undefined : onLine?.get(at)
                return (
                    <Fragment key={`line-${piece.hunk}-${piece.from + k}`}>
                        <Line
                            line={line}
                            tokens={highlighted?.[piece.hunk]?.[piece.from + k]}
                            changed={changed[piece.hunk]?.[piece.from + k]}
                            sides={sides}
                            add={
                                add === undefined || at === null
                                    ? undefined
                                    : { label: `Comment on ${file.path}:${at}`, pick: () => add(at) }
                            }
                        />
                        {cards !== undefined && (
                            <tr>
                                <td colSpan={columns} className="border-y bg-surface p-0">
                                    <InView className="flex flex-col gap-2 px-3 py-2 font-sans">
                                        {cards.map((item) => renderCard(item))}
                                    </InView>
                                </td>
                            </tr>
                        )}
                    </Fragment>
                )
            })
        }
        case 'fold': {
            return [
                <Fold
                    key={`fold-${piece.span.from}`}
                    span={piece.span}
                    columns={columns}
                    onShow={() => show(piece.span)}
                />,
            ]
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
function Fold({ span, columns, onShow }: { span: Span; columns: number; onShow: () => void }) {
    return (
        <tr className="border-y bg-surface-raised/50" data-testid="diff-fold">
            <td colSpan={columns} className="px-1 py-0.5">
                {/* At the panel's left edge, as a card is, while the lines scroll sideways. */}
                <FoldButton label={foldLabel(span)} onShow={onShow} className="sticky left-1" />
            </td>
        </tr>
    )
}

/**
 * One line of a hunk: its number on each of the file's `sides`, its mark, and its text, the words that `changed`
 * within it on a second layer of its tint. `add`, on a line of the new side, puts a + beside its number, shown while
 * the row is hovered or the button focused, which starts a comment on it.
 */
function Line({
    line,
    tokens,
    changed,
    sides,
    add,
}: {
    line: DiffLine
    tokens: CodeToken[] | undefined
    changed: readonly Changed[] | undefined
    sides: Sides
    add?: { label: string; pick: () => void }
}) {
    return (
        <tr className={cn('group', LINE_TINT[line.kind])} data-kind={line.kind}>
            {sides.old && <td className={NUMBER}>{line.old ?? ''}</td>}
            {sides.new && (
                <td className={NUMBER}>
                    {add === undefined ? (
                        (line.new ?? '')
                    ) : (
                        <span className="flex items-center justify-between gap-1">
                            <Button
                                variant="ghost"
                                size="icon-xs"
                                aria-label={add.label}
                                title={add.label}
                                onClick={add.pick}
                                className={cn(
                                    '-ml-1.5 size-4 text-accent opacity-0',
                                    'group-hover:opacity-100 focus-visible:opacity-100',
                                )}
                            >
                                <Plus />
                            </Button>
                            {line.new}
                        </span>
                    )}
                </td>
            )}
            <td aria-hidden className={cn('w-px border-l pr-1.5 pl-2 select-none', LINE_MARK[line.kind])}>
                {MARK[line.kind]}
            </td>
            <td className="pr-3 whitespace-pre" data-highlighted={tokens !== undefined || undefined}>
                {changed === undefined || changed.length === 0 ? (
                    <Code text={line.text} tokens={tokens} />
                ) : (
                    // A line's parts never reorder.
                    lineParts(line.text, tokens, changed).map((part, i) =>
                        part.changed ? (
                            <span key={i} className={WORD[line.kind]}>
                                {part.text}
                            </span>
                        ) : (
                            <Code key={i} text={part.text} tokens={part.tokens} />
                        ),
                    )
                )}
            </td>
        </tr>
    )
}

// A line number's cell, as narrow as the file's longest number and no narrower than three digits.
const NUMBER = 'w-px min-w-10 pr-2 pl-3 text-right whitespace-nowrap text-muted-foreground tabular-nums select-none'

/** A stretch of a line: its tokens colored once its file's grammar has read it, its plain text until then. */
function Code({ text, tokens }: { text: string; tokens: readonly CodeToken[] | undefined }) {
    return tokens === undefined ? text : <CodeTokens tokens={tokens} />
}

/**
 * One finding: its number and severity, its title and where, and its detail as rich text, as an agent wrote it. A small
 * button at the end of its head line dismisses it, so no worker or tick acts on it; a dismissed one says so. `pick`, a
 * checkbox, leads its head line when the card is the findings list's row itself, as on a review with no diff kept.
 */
export function FindingCard({
    run,
    numbered,
    pick,
    className,
}: {
    run: number
    numbered: Numbered
    pick?: ReactNode
    className?: string
}) {
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
                {pick}
                <span className="readout text-xs text-muted-foreground">{n}</span>
                <Chip tone={SEVERITY_TONE[finding.severity]}>{finding.severity}</Chip>
                <span className={cn('font-medium', finding.dismissed && 'text-muted-foreground')}>{finding.title}</span>
                {finding.location && (
                    <span className="font-mono text-xs break-all text-muted-foreground">{finding.location}</span>
                )}
                {finding.dismissed && <Chip>{dismissedLabel(finding)}</Chip>}
                {finding.held && <Chip tone="blocked">{HELD}</Chip>}
                <span className="ml-auto">{button}</span>
            </header>
            {finding.detail && <RichText text={finding.detail} className="mt-1.5 text-muted-foreground" />}
            <FindingAnswer finding={finding} />
            {notice}
        </article>
    )
}

/**
 * A held finding's chip: canopy holds a rebuttal of a worker's decline, or a late finding, for the operator (DESIGN
 * §21).
 */
export const HELD = 'held for you'

/**
 * What the latest worker handed a finding answered of it, `fixed` or `declined`, and its reason, in its words: what the
 * next review read beside the finding. Nothing when no worker answered it.
 */
function FindingAnswer({ finding }: { finding: Numbered['finding'] }) {
    if (finding.answer === null) {
        return null
    }
    return (
        <div className="mt-1.5 border-l-2 pl-2 text-xs text-muted-foreground" data-testid="finding-answer">
            <p>The worker answered: {finding.answer}</p>
            {finding.answer_reason !== null && <RichText text={finding.answer_reason} className="mt-1" />}
        </div>
    )
}
