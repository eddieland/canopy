import { useQuery } from '@tanstack/react-query'
import type { QueryKey, UseQueryOptions } from '@tanstack/react-query'
import { Link, useLocation } from '@tanstack/react-router'
import { useEffect, useState } from 'react'

import { ApiError } from '@/api/client'
import type { ChangedFile, ReviewDiff, RunChange, RunRange } from '@/api/types'
import { Disclosure } from '@/components/disclosure'
import { Empty, Panel, PanelHeader, PanelLoading } from '@/components/panel'
import { DiffPanels } from '@/components/review-diff'
import { Chip } from '@/components/status'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { pullRequestUrl } from '@/lib/pull-request-label'
import type { Placed } from '@/lib/reviews'
import {
    changedPath,
    DIFF_UNREAD,
    diffAnchor,
    filesLeftOutText,
    filesText,
    linesText,
    missingText,
    NO_CHANGE,
    NOT_COUNTED,
    NOT_ON_ORIGIN,
    NOTHING_RECORDED,
    rangeText,
    rangeTitle,
} from '@/lib/run-changes'

// A run that recorded nothing: a stable default.
const NO_CHANGES: readonly RunChange[] = []
// Nothing is placed on a run's diff: it is read for itself.
const NOTHING_PLACED: Placed<never> = { lines: new Map(), files: new Map(), elsewhere: [] }

/** The read of one repository's diff, which a page makes for its own kind of run: a worker's or a task's. */
export type ChangeQuery<K extends QueryKey> = (repo: string) => UseQueryOptions<ReviewDiff, Error, ReviewDiff, K>

/**
 * What a worker's or a task's run changed (DESIGN §45), a Diff panel per repository it recorded, by repository: a
 * summary, since a run's page is opened to see why the run ended far more often than to read its diff. Its header
 * names the repository, the commits, and how many files and lines changed, marks a slot the run left unpushed, and
 * links to the PR's page, where the branch against its base is; under it, each file with its lines. `Show diff` reads
 * the run's own diff (`diff`) and opens it under the panel, in the panels a review's diff has (`DiffPanels`); a page
 * opened at `#diff-<repo>` opens that one. A diff canopy did not keep says why, or that retention removed it, rather
 * than offering nothing. A run that recorded nothing says so when `records`, as an ended run of a kind that records
 * would have; otherwise, and while it runs, there is no panel.
 */
export function RunChangesPanel<K extends QueryKey>({
    changes = NO_CHANGES,
    records,
    diff,
}: {
    changes?: readonly RunChange[]
    records: boolean
    diff: ChangeQuery<K>
}) {
    if (changes.length === 0) {
        return records ? (
            <Panel data-testid="run-change">
                <PanelHeader label="Diff" />
                <Empty>{NOTHING_RECORDED}</Empty>
            </Panel>
        ) : null
    }
    return (
        <>
            {changes.map((change) => (
                <ChangeSummary key={change.range.repo} change={change} diff={diff} />
            ))}
        </>
    )
}

/** One repository's change: its summary panel, then its diff once opened. */
function ChangeSummary<K extends QueryKey>({ change, diff }: { change: RunChange; diff: ChangeQuery<K> }) {
    const { range } = change
    const anchor = diffAnchor(range.repo)
    const hash = useLocation({ select: (location) => location.hash })
    const [open, setOpen] = useState(change.diff_kept && hash === anchor)
    // A link to this repository's diff (`#diff-web`) opens it, and brings it into view once the page has drawn it.
    const [seen, setSeen] = useState(hash)
    if (hash !== seen) {
        setSeen(hash)
        if (hash === anchor && change.diff_kept) {
            setOpen(true)
        }
    }
    useEffect(() => {
        if (hash === anchor) {
            document.querySelector(`#${CSS.escape(anchor)}`)?.scrollIntoView({ block: 'start' })
        }
    }, [hash, anchor])
    const missing = missingText(change)
    const counted = range.files_changed
    const leftOut = filesLeftOutText(change)
    return (
        <Collapsible asChild open={open} onOpenChange={setOpen}>
            <section id={anchor} aria-label={`Diff: ${rangeText(range)}`} className="flex scroll-mt-4 flex-col gap-6">
                <Panel data-testid="run-change">
                    <PanelHeader label="Diff">
                        <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1">
                            <span
                                className="truncate readout text-xs text-muted-foreground"
                                title={rangeTitle(range)}
                                data-testid="run-change-range"
                            >
                                {rangeText(range)}
                            </span>
                            <ChangeSize range={range} />
                            {range.unpushed_sha !== null && <Chip word="not on origin" meaning={NOT_ON_ORIGIN} />}
                        </span>
                        <span className="flex items-center gap-3">
                            {change.pr_url !== null && (
                                <Link
                                    to="/pull-requests/pr"
                                    search={{ url: pullRequestUrl(change.pr_url) ?? change.pr_url }}
                                    title="The PR's page: its branch against its base now, with its threads"
                                    className="font-mono text-xs text-accent underline-offset-4 hover:underline"
                                >
                                    branch vs base
                                </Link>
                            )}
                            {change.diff_kept && <Disclosure open={open} what="diff" />}
                        </span>
                    </PanelHeader>
                    {counted === null ? (
                        <Empty>{missing === '' ? NOT_COUNTED : missing}</Empty>
                    ) : counted === 0 ? (
                        <Empty>{NO_CHANGE}</Empty>
                    ) : (
                        <>
                            <ul className="flex flex-col py-1.5" data-testid="run-change-files">
                                {change.files.map((file) => (
                                    <ChangedFileRow key={`${file.old_path ?? ''}:${file.path}`} file={file} />
                                ))}
                            </ul>
                            {leftOut !== '' && (
                                <p className="border-t px-3 py-2 font-mono text-xs text-muted-foreground">{leftOut}</p>
                            )}
                            {missing !== '' && (
                                <p className="border-t px-3 py-2 text-sm text-muted-foreground">{missing}</p>
                            )}
                        </>
                    )}
                </Panel>
                {change.diff_kept && (
                    <CollapsibleContent>
                        <ChangeDiff query={diff(range.repo)} />
                    </CollapsibleContent>
                )}
            </section>
        </Collapsible>
    )
}

/** How many files and lines a change touched, `2 files · +21 −3`, its counts in the diff's own colors. */
function ChangeSize({ range }: { range: RunRange }) {
    if (range.files_changed === null || range.files_changed === 0) {
        return null
    }
    const [added, removed] = linesText(range.lines_added ?? 0, range.lines_removed ?? 0)
    return (
        <span className="readout text-xs whitespace-nowrap text-muted-foreground" data-testid="run-change-size">
            {filesText(range)} · <span className="text-diff-add">{added}</span>{' '}
            <span className="text-diff-del">{removed}</span>
        </span>
    )
}

/** One file of a change: its path, cut from the left so its name shows, and its lines added and removed. */
function ChangedFileRow({ file }: { file: ChangedFile }) {
    const path = changedPath(file)
    const lines = file.added === null || file.removed === null ? null : linesText(file.added, file.removed)
    return (
        <li className="flex items-baseline justify-between gap-3 px-3 py-0.5 font-mono text-xs">
            <span className="min-w-0 truncate [direction:rtl]" title={path}>
                {/* The marks keep a path that starts or ends in punctuation reading left to right. */}
                <bdi>{path}</bdi>
            </span>
            {lines === null ? (
                <span className="shrink-0 text-muted-foreground">binary</span>
            ) : (
                <span className="shrink-0 whitespace-nowrap">
                    <span className="text-diff-add">{lines[0]}</span> <span className="text-diff-del">{lines[1]}</span>
                </span>
            )}
        </li>
    )
}

/** The run's own diff, read when opened: the file panels a review's diff has, or why it could not be read. */
function ChangeDiff<K extends QueryKey>({ query }: { query: UseQueryOptions<ReviewDiff, Error, ReviewDiff, K> }) {
    const read = useQuery(query)
    if (read.data === undefined) {
        // A diff the server no longer has is no read to try again: say so, as the panel would have.
        return read.error instanceof ApiError && read.error.status === 404 ? (
            <Panel>
                <Empty>{DIFF_UNREAD}</Empty>
            </Panel>
        ) : (
            <Panel>
                <PanelLoading query={read} rows={4} />
            </Panel>
        )
    }
    return read.data.files.length === 0 ? (
        <Panel>
            <Empty>{NO_CHANGE}</Empty>
        </Panel>
    ) : (
        <DiffPanels diff={read.data} placed={NOTHING_PLACED} cards={['note', 'notes']} renderCard={() => null} />
    )
}
