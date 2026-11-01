import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'

import { checklistCountsQuery } from '@/api/queries'
import type { ChecklistCounts, ChecklistItemCounts, ChecklistRun, ChecklistWeek } from '@/api/types'
import { Age } from '@/components/age'
import { ChartTable } from '@/components/chart-table'
import { Code } from '@/components/code'
import { DayChart, DayChartLegend } from '@/components/day-chart'
import { LinkedText } from '@/components/linked-text'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelScroll } from '@/components/panel'
import { ReadoutTiles } from '@/components/readout-tiles'
import type { ReadoutTile } from '@/components/readout-tiles'
import { RepoFilter } from '@/components/repo-picker'
import { RunLink } from '@/components/run-link'
import { TaskRunLink } from '@/components/task-link'
import { Clipped, Hinted, Tip } from '@/components/tip'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import {
    ANSWER_COLUMNS,
    answersByWeek,
    answersWords,
    CHECKLIST_SORTS,
    CHECKLIST_WINDOWS,
    checklistDays,
    checklistFigures,
    checklistLine,
    checklistSort,
    checklistVerdict,
    DEFAULT_CHECKLIST_DAYS,
    itemKey,
    itemsByRepo,
    pickedItem,
    sortGroups,
    weekBars,
    weekLabel,
} from '@/lib/checklist'
import type { AnswerColumn, ChecklistSort, RepoItems, WeekAnswers } from '@/lib/checklist'
import { counted } from '@/lib/descriptions'
import { reposOf } from '@/lib/pull-request-filter'
import { readoutDelta, wholeChange } from '@/lib/readout-delta'
import { repoListFrom, repoListOf, reposIn, reposWords } from '@/lib/repo-filter'
import { windowBefore, windowName } from '@/lib/report-window'
import { cn } from '@/lib/utils'

interface ChecklistSearch {
    days?: number | undefined
    repo?: string | undefined
    sort?: ChecklistSort | undefined
    item?: string | undefined
}

// What the page shows on every visit, on its title's hover: its description is the window's state.
const HELP =
    "How worker runs answered each repository's checklist, item by item: the runs reminded of it, then how many " +
    'answered pass, fixed, held, or n/a, and how many said nothing, as a bar and as counts. An item mostly n/a or ' +
    'never failing is one to reword or drop; one often held is one to argue. Pick an item for its answers by week. ' +
    'As canopy checklist --days N prints it.'

// What the runs reminded count, in its name's tip.
const REMINDED_HINT =
    'The runs given the item, by when they started: each answered it, or is counted unanswered. A run still ' +
    'running has answered nothing yet'

// The column names of a table in a padded scrolling region, as the spend page's: the region's top padding is the
// head's cells', so the rows scrolling under the sticky head never show above it.
const PADDED_HEAD = 'sticky top-0 bg-surface [&_th]:pt-3'
const HEAD = 'panel-label pb-1.5 pl-3 font-normal whitespace-nowrap'

// What the verdict column says, in its name's tip.
const VERDICT_HINT =
    'What the guide would say: drop? for an item given ten times or more that is mostly n/a or never failed, argue ' +
    'for one held twice or more'

/**
 * How worker runs answered each repository's checklist (DESIGN §42), as `canopy checklist` counts them: per repository
 * and item of its list, the runs reminded of it and how many answered each way, as a bar and as counts, with the
 * runs behind its held and fixed answers; and the answers by week, of one item or the whole list. `?days=` is the
 * window, 7 or 30 local days (two weeks when absent), `?repo=` keeps its repositories' lists, `?sort=` orders each
 * list's items (the list's order when absent), and `?item=` picks the item shown by week (`api:newspaper-order`).
 */
export const Route = createFileRoute('/reports/checklist')({
    validateSearch: (search: Record<string, unknown>): ChecklistSearch => ({
        days: checklistDays(search['days']),
        repo: repoListOf(search['repo']),
        sort: checklistSort(search['sort']),
        item: typeof search['item'] === 'string' && search['item'] !== '' ? search['item'] : undefined,
    }),
    component: ChecklistPage,
})

function ChecklistPage() {
    const search = Route.useSearch()
    const navigate = Route.useNavigate()
    const days = search.days ?? DEFAULT_CHECKLIST_DAYS
    const query = useQuery(checklistCountsQuery(days))
    const { data } = query
    // What the empty panels say they looked over: `these 7 days`.
    const span = windowName({ days })
    // A read that failed with nothing on screen says so once, in the panel, with Read again: no tiles held for it.
    const failed = data === undefined && query.error !== null
    return (
        <>
            <PageHeader
                title="Checklist"
                help={HELP}
                controls={
                    <ToggleGroup
                        type="single"
                        value={String(days)}
                        aria-label="Window"
                        onValueChange={(value) => {
                            const n = CHECKLIST_WINDOWS.find((w) => String(w) === value)
                            // Pressing the window shown turns it off: keep it. Two weeks, the default, need no
                            // search; the repository filter, the order, and the item picked stay as they are.
                            if (n !== undefined) {
                                void navigate({
                                    search: (prev) => ({
                                        ...prev,
                                        days: n === DEFAULT_CHECKLIST_DAYS ? undefined : n,
                                    }),
                                })
                            }
                        }}
                    >
                        {CHECKLIST_WINDOWS.map((n) => (
                            <ToggleGroupItem key={n} value={String(n)} data-testid={`checklist-window-${n}`}>
                                {windowName({ days: n })}
                            </ToggleGroupItem>
                        ))}
                    </ToggleGroup>
                }
                links={
                    !failed && (
                        <ReadoutTiles
                            tiles={checklistTiles(data)}
                            against={windowBefore({ days })}
                            testId="checklist"
                        />
                    )
                }
            >
                {data === undefined
                    ? query.isPending
                        ? 'reading the answers'
                        : null
                    : checklistLine(data.items, data.days)}
            </PageHeader>
            <Panel data-testid="checklist-items">
                <PanelHeader label="By item">
                    {data !== undefined && data.items.length > 0 && (
                        <div className="flex flex-wrap items-center gap-2">
                            <SortToggle />
                            <Filter repos={reposOf(data.items, search.repo)} />
                        </div>
                    )}
                </PanelHeader>
                {data === undefined ? (
                    <PanelLoading query={query} rows={6} className="min-h-40" />
                ) : data.items.length === 0 ? (
                    <Empty size="panel">
                        no worker run of these {span} was given a checklist: each repository&apos;s is a file in{' '}
                        <Code>paths.checklists</Code>
                    </Empty>
                ) : (
                    <Items
                        groups={sortGroups(itemsByRepo(data.items, search.repo), search.sort ?? 'list')}
                        repo={search.repo}
                        span={span}
                    />
                )}
            </Panel>
            {data !== undefined && data.items.length > 0 && (
                <ByWeek
                    weeks={data.weeks}
                    picked={pickedItem(itemsByRepo(data.items, search.repo), search.item)}
                    repo={search.repo}
                />
            )}
        </>
    )
}

/**
 * The window's headline figures over every repository's list, each held in its place while the counts are read, and
 * each against the window before's: fewer items held, or left unanswered, is better.
 */
function checklistTiles(found: ChecklistCounts | undefined): ReadoutTile[] {
    const figures = found === undefined ? undefined : checklistFigures(found.items)
    const before = found?.previous
    return [
        {
            key: 'reminded',
            label: 'items given',
            hint: "How many times a run was given an item of its repositories' lists",
            value: figures?.reminded,
            delta: readoutDelta(figures?.reminded, before?.reminded, wholeChange),
        },
        {
            key: 'held',
            label: 'held',
            hint: 'Of those, the ones a run left failing, for a reason it gave',
            value: figures?.held,
            delta: readoutDelta(figures?.held, before?.held, wholeChange, 'down'),
        },
        {
            key: 'unanswered',
            label: 'unanswered',
            hint: "Of those, the ones a run's result said nothing of",
            value: figures?.unanswered,
            delta: readoutDelta(figures?.unanswered, before?.unanswered, wholeChange, 'down'),
        },
    ]
}

/** The repository picker, kept in `?repo=`, while the lists counted are more than one repository's (`RepoFilter`). */
function Filter({ repos }: { repos: string[] }) {
    const search = Route.useSearch()
    const navigate = Route.useNavigate()
    if (repos.length < 2) {
        return null
    }
    return (
        <RepoFilter
            repos={repos}
            chosen={reposIn(search.repo)}
            onChoose={(chosen) =>
                void navigate({ search: (prev) => ({ ...prev, repo: repoListFrom(chosen) }), replace: true })
            }
        />
    )
}

/** The By item table's order, kept in `?sort=`: the list's own, or the most held, n/a, or unanswered first. */
function SortToggle() {
    const search = Route.useSearch()
    const navigate = Route.useNavigate()
    return (
        <ToggleGroup
            type="single"
            value={search.sort ?? 'list'}
            aria-label="Sort"
            onValueChange={(value) => {
                const picked = CHECKLIST_SORTS.find((s) => s.key === value)
                // Pressing the order shown turns it off: keep it. The list's own order needs no search.
                if (picked !== undefined) {
                    void navigate({
                        search: (prev) => ({ ...prev, sort: picked.key === 'list' ? undefined : picked.key }),
                        replace: true,
                        resetScroll: false,
                    })
                }
            }}
        >
            {CHECKLIST_SORTS.map((s) => (
                <ToggleGroupItem key={s.key} value={s.key} data-testid={`checklist-sort-${s.key}`}>
                    {s.label}
                </ToggleGroupItem>
            ))}
        </ToggleGroup>
    )
}

/**
 * One table of every repository's items, a group of rows each, under its name and how many items it has: an item, the
 * runs reminded of it, a bar of its answers, each answer's count in `canopy checklist`'s columns, and the guide's
 * verdict. A count of none is muted, so what was answered stands out; a held or fixed count opens the runs behind it.
 * An item's name picks it for By week. The bar's legend is under the table, once.
 */
function Items({ groups, repo, span }: { groups: RepoItems[]; repo: string | undefined; span: string }) {
    if (groups.length === 0) {
        return (
            <Empty size="panel">
                no run in {reposWords(repo ?? '')} was given a checklist in these {span}
            </Empty>
        )
    }
    return (
        <div className="flex flex-col">
            <PanelScroll label="Checklist answers by item" className="px-3 pb-3">
                <table className="border-collapse text-sm" data-testid="checklist-table">
                    <thead className={PADDED_HEAD}>
                        <tr className="text-right">
                            <th className="panel-label pb-1.5 text-left font-normal">item</th>
                            <th className={HEAD}>
                                <Hinted hint={REMINDED_HINT}>reminded</Hinted>
                            </th>
                            <th className={cn(HEAD, 'text-left')}>answers</th>
                            {ANSWER_COLUMNS.map((c) => (
                                <th key={c.key} className={HEAD}>
                                    <Hinted hint={c.hint}>{c.label}</Hinted>
                                </th>
                            ))}
                            <th className={cn(HEAD, 'text-left')}>
                                <Hinted hint={VERDICT_HINT}>verdict</Hinted>
                            </th>
                        </tr>
                    </thead>
                    {groups.map((group, i) => (
                        <tbody key={group.repo} className="font-mono text-xs" data-testid="checklist-repo">
                            <tr>
                                <th
                                    scope="rowgroup"
                                    colSpan={ANSWER_COLUMNS.length + 4}
                                    className={cn('pb-1 text-left font-medium text-foreground', i > 0 && 'pt-4')}
                                >
                                    {group.repo}
                                    <span className="ml-2 font-normal text-muted-foreground">
                                        {counted(group.items.length, 'item')}
                                    </span>
                                </th>
                            </tr>
                            {group.items.map((item) => (
                                <ItemRow key={item.item} item={item} />
                            ))}
                        </tbody>
                    ))}
                </table>
            </PanelScroll>
            <div className="px-3 pb-3">
                <DayChartLegend series={ANSWER_COLUMNS} testId="checklist" />
            </div>
        </div>
    )
}

/** An item's row: its name, which picks it, the runs reminded, its answer bar, each answer's count, its verdict. */
function ItemRow({ item }: { item: ChecklistItemCounts }) {
    const verdict = checklistVerdict(item)
    return (
        <tr className="text-right" data-testid="checklist-item">
            <th scope="row" className="py-0.5 text-left font-normal">
                {/* The router marks the picked one's link `aria-current="page"`: its search is the page's own. */}
                <Link
                    to="/reports/checklist"
                    search={(prev) => ({ ...prev, item: itemKey(item) })}
                    replace
                    resetScroll={false}
                    className={cn(
                        'block max-w-lg rounded-sm px-1 text-accent underline-offset-4 hover:underline',
                        'aria-[current=page]:bg-accent/16 aria-[current=page]:text-foreground',
                    )}
                >
                    {/* The row's name, as the spend page's tools read: medium weight, cut to fit. */}
                    <Clipped text={item.item} className="block font-sans font-medium" />
                </Link>
            </th>
            <td className="readout pl-3">{item.reminded}</td>
            <td className="pl-3">
                <AnswerBar item={item} />
            </td>
            {ANSWER_COLUMNS.map((c) => (
                <td key={c.key} className={cn('readout pl-3', item[c.key] === 0 && 'text-muted-foreground')}>
                    <AnswerCount item={item} column={c} />
                </td>
            ))}
            <td className="pl-3 text-left font-sans text-muted-foreground" data-testid="checklist-verdict">
                {verdict !== null && <Hinted hint={verdict.why}>{verdict.word}</Hinted>}
            </td>
        </tr>
    )
}

/**
 * An item's answers as a bar of its runs, each answer its share in its fill, in the table's order (ui/DESIGN.md, "A
 * bar in a cell"): all n/a is one grey bar, all pass one green one, often held a red band. The counts are in the
 * row, and in words on its hover; with no run reminded, an empty well.
 */
function AnswerBar({ item }: { item: ChecklistItemCounts }) {
    const words = answersWords(item)
    return (
        <Tip fact={words}>
            <span className="flex h-2 w-32 overflow-hidden rounded-full bg-surface-raised" data-testid="checklist-bar">
                <span className="sr-only">{words}</span>
                {item.reminded > 0 &&
                    ANSWER_COLUMNS.filter((c) => item[c.key] > 0).map((c) => (
                        <span
                            key={c.key}
                            aria-hidden
                            className={cn('h-full not-last:border-r-2 not-last:border-surface', c.fill)}
                            style={{ width: `${(item[c.key] / item.reminded) * 100}%` }}
                            data-testid={`checklist-bar-${c.key}`}
                        />
                    ))}
            </span>
        </Tip>
    )
}

/**
 * An answer's count. A held or fixed count of some opens the runs that gave it, the newest first, a held one's reason
 * under its run: why it held is the worker's word, and the run has it whole. The rest are figures alone.
 */
function AnswerCount({ item, column }: { item: ChecklistItemCounts; column: AnswerColumn }) {
    const count = item[column.key]
    const runs = column.key === 'held' ? item.held_runs : column.key === 'fixed' ? item.fixed_runs : []
    if (count === 0 || runs.length === 0) {
        return count
    }
    return (
        <Popover>
            <PopoverTrigger
                className="rounded-sm text-accent underline-offset-4 hover:underline"
                aria-label={`${count} ${column.label}: the runs`}
                data-testid={`checklist-${column.key}-runs`}
            >
                {count}
            </PopoverTrigger>
            <PopoverContent align="end" className="w-96 p-3 text-left font-sans">
                <p className="panel-label pb-2">
                    {column.label} · {item.item}
                    {count > runs.length && ` · the newest ${runs.length} of ${count}`}
                </p>
                <ul className="flex max-h-80 flex-col gap-2 overflow-y-auto" data-testid="checklist-runs">
                    {runs.map((run) => (
                        <AnsweringRun key={`${run.kind}-${run.id}`} run={run} />
                    ))}
                </ul>
            </PopoverContent>
        </Popover>
    )
}

/** One run behind an answer: its link, when it started, and the reason it held the item, if it gave one. */
function AnsweringRun({ run }: { run: ChecklistRun }) {
    return (
        <li className="flex flex-col gap-0.5">
            <span className="flex items-baseline gap-2">
                {run.kind === 'task' && run.task_id !== null ? (
                    <TaskRunLink task={run.task_id} run={run.id} />
                ) : (
                    <RunLink id={run.id} />
                )}
                <Age at={run.started_at} variant="ago" />
            </span>
            {run.reason !== null && (
                <span className="text-xs break-words text-muted-foreground">
                    <LinkedText text={run.reason} />
                </span>
            )}
        </li>
    )
}

/**
 * The answers by week: the picked item's, or the whole list's the filter keeps, a bar a week stacked in the answer
 * fills, so a rewrite that took shows as the week its bar changed color. Its table folds under it.
 */
function ByWeek({
    weeks,
    picked,
    repo,
}: {
    weeks: ChecklistWeek[]
    picked: ChecklistItemCounts | undefined
    repo: string | undefined
}) {
    const found = answersByWeek(weeks, picked, repo)
    return (
        <Panel data-testid="checklist-weeks">
            <PanelHeader label="By week">
                <span className="flex items-center gap-3 text-xs">
                    <span className="readout text-muted-foreground" data-testid="checklist-weeks-of">
                        {picked === undefined ? 'every item' : `${picked.repo} · ${picked.item}`}
                    </span>
                    {picked !== undefined && (
                        <Link
                            to="/reports/checklist"
                            search={(prev) => ({ ...prev, item: undefined })}
                            // Not the page shown while an item is: its search drops the item rather than matching it.
                            activeOptions={{ explicitUndefined: true }}
                            replace
                            resetScroll={false}
                            className="text-accent underline-offset-4 hover:underline"
                        >
                            every item
                        </Link>
                    )}
                </span>
            </PanelHeader>
            <div className="flex flex-col gap-4 p-3">
                {/* Measured afresh for each window: another count of bars is another pitch. */}
                <DayChart key={found.length} bars={weekBars(found)} testId="checklist-week" />
                <DayChartLegend series={ANSWER_COLUMNS} testId="checklist-week" />
                <ChartTable
                    what={counted(found.length, 'week')}
                    label="Checklist answers by week"
                    className="max-h-60 overflow-x-auto"
                >
                    <WeekTable weeks={found} />
                </ChartTable>
            </div>
        </Panel>
    )
}

/** The chart by week's numbers: each week, the items given, and each answer's count. */
function WeekTable({ weeks }: { weeks: WeekAnswers[] }) {
    return (
        <table className="border-collapse text-sm" data-testid="checklist-week-table">
            <thead className="sticky top-0 bg-surface">
                <tr className="text-right">
                    <th className="panel-label pb-1.5 text-left font-normal">week</th>
                    <th className={HEAD}>given</th>
                    {ANSWER_COLUMNS.map((c) => (
                        <th key={c.key} className={HEAD}>
                            {c.label}
                        </th>
                    ))}
                </tr>
            </thead>
            <tbody className="font-mono text-xs">
                {weeks.map((w) => (
                    <tr key={w.week} className="text-right">
                        <th scope="row" className="py-0.5 text-left font-normal">
                            {weekLabel(w.week)}
                        </th>
                        <td className="readout pl-3">{w.reminded}</td>
                        {ANSWER_COLUMNS.map((c) => (
                            <td key={c.key} className={cn('readout pl-3', w[c.key] === 0 && 'text-muted-foreground')}>
                                {w[c.key]}
                            </td>
                        ))}
                    </tr>
                ))}
            </tbody>
        </table>
    )
}
