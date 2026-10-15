import { Fragment } from 'react'

import type { DiffFile, DiffLine, ReviewDiff } from '@/api/types'
import { useDismissReviewFinding } from '@/components/dismiss-finding'
import { Panel, PanelHeader } from '@/components/panel'
import { RichText } from '@/components/rich-text'
import { Chip } from '@/components/status'
import { findingAnchor, SEVERITY_TONE } from '@/lib/reviews'
import type { Numbered, Placed } from '@/lib/reviews'
import { cn } from '@/lib/utils'

// Full class names, written out, so Tailwind finds them: a line's tint and its +/- mark.
const LINE_TINT: Record<DiffLine['kind'], string> = { add: 'bg-diff-add/12', del: 'bg-diff-del/12', ctx: '' }
const LINE_MARK: Record<DiffLine['kind'], string> = { add: 'text-diff-add', del: 'text-diff-del', ctx: '' }
const MARK: Record<DiffLine['kind'], string> = { add: '+', del: '-', ctx: ' ' }

/**
 * The reviewed commit's diff, a panel per file, with each finding's card under the line it names, or under the file's
 * header when the diff does not show its line. The diff is the PR's own text: every line is React text.
 */
export function ReviewDiffPanels({ run, diff, placed }: { run: number; diff: ReviewDiff; placed: Placed }) {
    return (
        <>
            {diff.files.map((file, i) => (
                <FilePanel
                    key={`${i}:${file.path}`}
                    run={run}
                    file={file}
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
    onLine,
    onFile,
}: {
    run: number
    file: DiffFile
    onLine: Map<number, Numbered[]> | undefined
    onFile: Numbered[]
}) {
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
            {file.hunks.length > 0 && (
                <div className="overflow-x-auto">
                    <table className="w-full border-collapse font-mono text-xs">
                        <tbody>
                            {file.hunks.map((hunk, h) => (
                                <Fragment key={h}>
                                    <tr className="bg-surface-raised text-muted-foreground">
                                        <td colSpan={4} className="px-3 py-1 whitespace-pre">
                                            {hunk.header ? `@@ ${hunk.header}` : '@@'}
                                        </td>
                                    </tr>
                                    {hunk.lines.map((line, n) => (
                                        <Fragment key={n}>
                                            <Line line={line} />
                                            {line.new !== null && onLine?.get(line.new) && line.kind !== 'del' && (
                                                <tr>
                                                    <td colSpan={4} className="border-y bg-surface px-3 py-2">
                                                        <div className="flex flex-col gap-2 font-sans">
                                                            {onLine.get(line.new)?.map((f) => (
                                                                <FindingCard key={f.n} run={run} numbered={f} />
                                                            ))}
                                                        </div>
                                                    </td>
                                                </tr>
                                            )}
                                        </Fragment>
                                    ))}
                                </Fragment>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </Panel>
    )
}

function Line({ line }: { line: DiffLine }) {
    return (
        <tr className={LINE_TINT[line.kind]} data-kind={line.kind}>
            <td className="w-12 px-2 text-right text-muted-foreground tabular-nums select-none">{line.old ?? ''}</td>
            <td className="w-12 px-2 text-right text-muted-foreground tabular-nums select-none">{line.new ?? ''}</td>
            <td aria-hidden className={cn('w-4 select-none', LINE_MARK[line.kind])}>
                {MARK[line.kind]}
            </td>
            <td className="pr-3 whitespace-pre">{line.text}</td>
        </tr>
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
