import { useQuery } from '@tanstack/react-query'
import type { QueryKey, UseQueryOptions } from '@tanstack/react-query'
import { Link, useLocation } from '@tanstack/react-router'
import { useEffect, useState } from 'react'

import { ApiError } from '@/api/client'
import type { ChangedFile, ChecklistStretch, ReviewDiff, RunChange, RunRange } from '@/api/types'
import { Disclosure } from '@/components/disclosure'
import { Empty, Panel, PanelHeader, PanelLoading } from '@/components/panel'
import { DiffPanels } from '@/components/review-diff'
import { Chip } from '@/components/status'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { stretchesLeftOutText, stretchRange } from '@/lib/checklist'
import { pullRequestUrl } from '@/lib/pull-request-label'
import { goneText } from '@/lib/retention'
import type { Placed } from '@/lib/reviews'
import {
    changedAfterText,
    changedPath,
    DIFF_UNREAD,
    diffAnchor,
    diffsByRepo,
    filesLeftOutText,
    filesText,
    linesText,
    missingText,
    NO_CHANGE,
    NO_STRETCH,
    NO_STRETCH_CHANGE,
    NOT_COUNTED,
    NOT_ON_ORIGIN,
    NOTHING_RECORDED,
    rangeText,
    rangeTitle,
    scopeName,
    STRETCH,
    stretchFiles,
    stretchSpan,
} from '@/lib/run-changes'
import type { RepoDiff } from '@/lib/run-changes'
import { cn } from '@/lib/utils'

// A run that recorded nothing, or pushed nothing after a list: stable defaults.
const NO_CHANGES: readonly RunChange[] = []
const NO_STRETCHES: readonly ChecklistStretch[] = []
// Nothing is placed on a run's diff: it is read for itself.
const NOTHING_PLACED: Placed<never> = { lines: new Map(), files: new Map(), elsewhere: [] }
// The scope of the run's own diff, beside each stretch's.
const WHOLE_RUN = 'run'

/** The read of one repository's diff, which a page makes for its own kind of run: a worker's or a task's. */
export type ChangeQuery<K extends QueryKey> = (repo: string) => UseQueryOptions<ReviewDiff, Error, ReviewDiff, K>

/**
 * What a worker's or a task's run changed (DESIGN §45), a Diff panel per repository, by repository: a summary, since a
 * run's page is opened to see why the run ended far more often than to read its diff. Its header names the repository,
 * the commits, and how many files and lines changed, marks a slot the run left unpushed, and links to the PR's page,
 * where the branch against its base is; under it, each file with its lines. `Show diff` opens the diff's file panels
 * under the panel (`DiffPanels`), the run's own read then (`diff`); a page opened at `#diff-<repo>` opens that one.
 *
 * A run held by its list (DESIGN §42) pushed a stretch after it, part of what it changed: the panel of its repository
 * holds it as a scope, `after the list` beside `whole run`, and opens on it, its diff sent with the run, so the fix the
 * answers above speak of is read where the run's change is. A dot marks each file the stretch touched; a line under the
 * files names its commits, or says why it has no diff. How many stretches the page was not sent, which
 * `canopy show <shownBy>` names, follows the panels.
 *
 * A diff canopy did not keep says why, or that retention removed it, rather than offering nothing. A run that recorded
 * nothing says so when `records`, as an ended run of a kind that records would have; otherwise, and while it runs,
 * there is no panel.
 */
export function RunChangesPanel<K extends QueryKey>({
    changes = NO_CHANGES,
    records,
    diff,
    stretches = NO_STRETCHES,
    leftOut = 0,
    shownBy = '',
}: {
    changes?: readonly RunChange[]
    records: boolean
    diff: ChangeQuery<K>
    stretches?: readonly ChecklistStretch[]
    leftOut?: number
    shownBy?: string
}) {
    const repos = diffsByRepo(changes, stretches)
    return (
        <>
            {repos.length === 0 && records && (
                <Panel data-testid="run-change">
                    <PanelHeader label="Diff" />
                    <Empty>{NOTHING_RECORDED}</Empty>
                </Panel>
            )}
            {repos.map((repo) => (
                <RepoDiffSection key={repo.repo} repo={repo} records={records} diff={diff} />
            ))}
            {leftOut > 0 && (
                <p className="font-mono text-xs text-muted-foreground" data-testid="checklist-stretches-left-out">
                    {stretchesLeftOutText(leftOut, shownBy)}
                </p>
            )}
        </>
    )
}

/** One repository's Diff: its summary panel, then the diff of the scope it shows once opened. */
function RepoDiffSection<K extends QueryKey>({
    repo: { repo, change, stretches },
    records,
    diff,
}: {
    repo: RepoDiff
    records: boolean
    diff: ChangeQuery<K>
}) {
    const anchor = diffAnchor(repo)
    const hash = useLocation({ select: (location) => location.hash })
    const kept = change?.diff_kept ?? false
    const linked = kept && hash === anchor
    // Each stretch's scope, by its index, then the run's own diff when there is one to read.
    const scopes = [...stretches.map((_, i) => String(i)), ...(kept ? [WHOLE_RUN] : [])]
    const [scope, setScope] = useState(linked || stretches.length === 0 ? WHOLE_RUN : '0')
    const [open, setOpen] = useState(linked || stretches.length > 0)
    // A link to this repository's diff (`#diff-web`) opens the run's own, and brings it into view once drawn.
    const [seen, setSeen] = useState(hash)
    if (hash !== seen) {
        setSeen(hash)
        if (hash === anchor && kept) {
            setScope(WHOLE_RUN)
            setOpen(true)
        }
    }
    useEffect(() => {
        if (hash === anchor) {
            document.querySelector(`#${CSS.escape(anchor)}`)?.scrollIntoView({ block: 'start' })
        }
    }, [hash, anchor])
    const stretch = scope === WHOLE_RUN ? null : (stretches[Number(scope)] ?? null)
    const stretchDiff = stretch?.diff ?? null
    const drawable = stretch === null ? kept : (stretchDiff?.files.length ?? 0) > 0
    // The files the stretch in view touched; none in view, but some to choose, keeps the dots' room, so no path moves.
    const marked = stretches.length === 0 ? null : new Set(stretchDiff?.files.map((file) => file.path))
    // With no change of its own to list, the panel lists the stretch's files.
    const ownFiles = change === null && stretchDiff !== null ? stretchFiles(stretchDiff) : []
    const listed = ownFiles.length > 0
    // The diff's file filter sits closer under the panel than the panels part, so it reads as this one's.
    return (
        <Collapsible asChild open={open} onOpenChange={setOpen}>
            <section id={anchor} aria-label={`${repo}'s diff`} className="flex scroll-mt-4 flex-col gap-3">
                <Panel data-testid="run-change">
                    <PanelHeader label="Diff">
                        <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1">
                            {change === null ? (
                                <span className="readout text-xs text-muted-foreground" data-testid="run-change-range">
                                    {repo}
                                </span>
                            ) : (
                                <ChangeReadout range={change.range} />
                            )}
                        </span>
                        <span className="flex items-center gap-3">
                            {change !== null && change.pr_url !== null && (
                                <Link
                                    to="/pull-requests/pr"
                                    search={{ url: pullRequestUrl(change.pr_url) ?? change.pr_url }}
                                    title="The PR's page: its branch against its base now, with its threads"
                                    className="font-mono text-xs text-accent underline-offset-4 hover:underline"
                                >
                                    branch vs base
                                </Link>
                            )}
                            {scopes.length > 1 && (
                                <ToggleGroup
                                    type="single"
                                    value={scope}
                                    aria-label={`Which of ${repo}'s diffs`}
                                    onValueChange={(value) => {
                                        // Pressing the scope shown turns it off, which reads as no value: keep it.
                                        if (value !== '') {
                                            setScope(value)
                                        }
                                    }}
                                    data-testid="run-change-scopes"
                                >
                                    {scopes.map((key) => {
                                        const shown = key === WHOLE_RUN ? undefined : stretches[Number(key)]
                                        return (
                                            <ToggleGroupItem
                                                key={key}
                                                value={key}
                                                className="font-mono"
                                                title={scopeTitle(shown, change)}
                                            >
                                                {scopeName(shown === undefined ? null : Number(key), stretches.length)}
                                            </ToggleGroupItem>
                                        )
                                    })}
                                </ToggleGroup>
                            )}
                            {drawable && <Disclosure open={open} what="diff" />}
                        </span>
                    </PanelHeader>
                    {change === null ? (
                        <>
                            {listed && <FileList files={ownFiles} marked={marked} />}
                            {records && (
                                <p className={cn('px-3 py-2 text-sm text-muted-foreground', listed && 'border-t')}>
                                    {NOTHING_RECORDED}
                                </p>
                            )}
                        </>
                    ) : (
                        <ChangeBody change={change} marked={marked} />
                    )}
                    {stretch !== null && <StretchLine stretch={stretch} under={change !== null || listed || records} />}
                </Panel>
                {drawable && (
                    <CollapsibleContent className="flex flex-col gap-6">
                        {stretchDiff === null ? (
                            <ChangeDiff query={diff(repo)} />
                        ) : (
                            <DiffPanels
                                diff={stretchDiff}
                                placed={NOTHING_PLACED}
                                cards={['note', 'notes']}
                                renderCard={() => null}
                                level={3}
                            />
                        )}
                    </CollapsibleContent>
                )}
            </section>
        </Collapsible>
    )
}

/** A scope's hover: a stretch's repository and commits and what a stretch is, or what the whole run's range spans. */
function scopeTitle(stretch: ChecklistStretch | undefined, change: RunChange | null): string | undefined {
    if (stretch !== undefined) {
        return `${stretchRange(stretch)}: ${STRETCH}`
    }
    return change === null ? undefined : rangeTitle(change.range)
}

/** A change's range, its hover saying what it runs from and to, its size, and whether it is on origin. */
function ChangeReadout({ range }: { range: RunRange }) {
    return (
        <>
            <span
                className="truncate readout text-xs text-muted-foreground"
                title={rangeTitle(range)}
                data-testid="run-change-range"
            >
                {rangeText(range)}
            </span>
            <ChangeSize range={range} />
            {range.unpushed_sha !== null && <Chip word="not on origin" meaning={NOT_ON_ORIGIN} />}
        </>
    )
}

/**
 * What a change's panel holds under its header: its files with their lines, the files past the bound the journal
 * keeps, and why a diff is missing; or that it changed nothing, or was never counted. `marked`, where a stretch can be
 * the scope shown, holds the paths of the files the one shown touched, none while the whole run is.
 */
function ChangeBody({ change, marked }: { change: RunChange; marked: ReadonlySet<string> | null }) {
    const missing = missingText(change)
    const counted = change.range.files_changed
    const leftOut = filesLeftOutText(change)
    if (counted === null) {
        return <Empty>{missing === '' ? NOT_COUNTED : missing}</Empty>
    }
    if (counted === 0) {
        return <Empty>{NO_CHANGE}</Empty>
    }
    return (
        <>
            <FileList files={change.files} marked={marked} />
            {leftOut !== '' && <p className="border-t px-3 py-2 font-mono text-xs text-muted-foreground">{leftOut}</p>}
            {missing !== '' && <p className="border-t px-3 py-2 text-sm text-muted-foreground">{missing}</p>}
        </>
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

/** A change's files, each a row; `marked`, where a stretch can be in view, the paths it touched, each with a dot. */
function FileList({ files, marked }: { files: readonly ChangedFile[]; marked: ReadonlySet<string> | null }) {
    return (
        <ul className="flex flex-col py-1.5" data-testid="run-change-files">
            {files.map((file) => (
                <ChangedFileRow
                    key={`${file.old_path ?? ''}:${file.path}`}
                    file={file}
                    marked={marked === null ? null : marked.has(file.path)}
                />
            ))}
        </ul>
    )
}

/**
 * One file of a change: its path, cut from the left so its name shows, and its lines added and removed. `marked`,
 * where a stretch can be in view, leads it with the stretch's dot if the one in view touched the file, and with the
 * dot's room if not, so the paths line up.
 */
function ChangedFileRow({ file, marked }: { file: ChangedFile; marked: boolean | null }) {
    const path = changedPath(file)
    const lines = file.added === null || file.removed === null ? null : linesText(file.added, file.removed)
    return (
        <li className="flex items-baseline justify-between gap-3 px-3 py-0.5 font-mono text-xs">
            <span className="flex min-w-0 items-baseline gap-2">
                {marked !== null && <StretchDot hidden={!marked} />}
                {marked === true && <span className="sr-only">changed after the list: </span>}
                <span className="min-w-0 truncate [direction:rtl]" title={path}>
                    {/* The marks keep a path that starts or ends in punctuation reading left to right. */}
                    <bdi>{path}</bdi>
                </span>
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

/** The mark of a file a stretch touched, in the checklist's `fixed` color: what a fix after the list changed. */
function StretchDot({ hidden = false }: { hidden?: boolean }) {
    return (
        <span
            aria-hidden
            className={hidden ? 'size-1.5 shrink-0' : 'size-1.5 shrink-0 self-center rounded-full bg-answer-fixed'}
        />
    )
}

/**
 * What the stretch in view is, under the files: how many it touched and its commits, its hover saying what a stretch
 * is; or that canopy kept no diff of it, retention removed it, or it changed nothing. `under` puts a hairline over it,
 * where something sits between it and the header.
 */
function StretchLine({ stretch, under }: { stretch: ChecklistStretch; under: boolean }) {
    const files = stretch.diff?.files.length ?? 0
    return (
        <p
            className={cn(
                'flex items-baseline gap-2 px-3 py-2 font-mono text-xs text-muted-foreground',
                under && 'border-t',
            )}
            title={STRETCH}
            data-testid="run-change-stretch"
        >
            {stretch.diff === null ? (
                goneText(stretch.diff_removed_after_days, NO_STRETCH)
            ) : files === 0 ? (
                NO_STRETCH_CHANGE
            ) : (
                <>
                    <StretchDot />
                    <span>
                        {changedAfterText(files)} · <span className="readout">{stretchSpan(stretch)}</span>
                    </span>
                </>
            )}
        </p>
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
        <DiffPanels
            diff={read.data}
            placed={NOTHING_PLACED}
            cards={['note', 'notes']}
            renderCard={() => null}
            level={3}
        />
    )
}
