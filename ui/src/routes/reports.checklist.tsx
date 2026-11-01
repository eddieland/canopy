import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { checklistCountsQuery } from '@/api/queries'
import { Code } from '@/components/code'
import { Empty, PageHeader, Panel, PanelHeader, PanelLoading, PanelScroll } from '@/components/panel'
import { RepoFilter } from '@/components/repo-picker'
import { Clipped, Hinted } from '@/components/tip'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import {
    ANSWER_COLUMNS,
    CHECKLIST_WINDOWS,
    checklistDays,
    checklistLine,
    DEFAULT_CHECKLIST_DAYS,
    itemsByRepo,
} from '@/lib/checklist'
import type { RepoItems } from '@/lib/checklist'
import { reposOf } from '@/lib/pull-request-filter'
import { repoListFrom, repoListOf, reposIn, reposWords } from '@/lib/repo-filter'
import { windowName } from '@/lib/report-window'
import { cn } from '@/lib/utils'

interface ChecklistSearch {
    days?: number | undefined
    repo?: string | undefined
}

// What the page shows on every visit, on its title's hover: its description is the window's state.
const HELP =
    "How worker runs answered each repository's checklist, item by item: the runs reminded of it, then how many " +
    'answered pass, fixed, held, or n/a, and how many said nothing. An item mostly n/a or never failing is one to ' +
    'reword or drop; one often held is one to argue. Why a run held an item is on its run. As canopy checklist ' +
    '--days N prints it.'

// What the runs reminded count, in its name's tip.
const REMINDED_HINT =
    'The runs given the item, by when they started: each answered it, or is counted unanswered. A run still ' +
    'running has answered nothing yet'

// The column names of a table in a padded scrolling region, as the spend page's: the region's top padding is the
// head's cells', so the rows scrolling under the sticky head never show above it.
const PADDED_HEAD = 'sticky top-0 bg-surface [&_th]:pt-3'
const HEAD = 'panel-label pb-1.5 pl-3 font-normal whitespace-nowrap'

/**
 * How worker runs answered each repository's checklist (DESIGN §42), as `canopy checklist` counts them: per repository
 * and item of its list, in the list's order, the runs reminded of it and how many answered each way. `?days=` is the
 * window, 14 or 30 local days (a week when absent), and `?repo=` keeps its repositories' lists. A held item's reason is
 * the worker's words and stays on its run, as the CLI keeps it off its table.
 */
export const Route = createFileRoute('/reports/checklist')({
    validateSearch: (search: Record<string, unknown>): ChecklistSearch => ({
        days: checklistDays(search['days']),
        repo: repoListOf(search['repo']),
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
                            // Pressing the window shown turns it off: keep it. A week, the default, needs no
                            // search; the repository filter stays as it is.
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
            >
                {data === undefined
                    ? query.isPending
                        ? 'reading the answers'
                        : null
                    : checklistLine(data.items, data.days)}
            </PageHeader>
            <Panel data-testid="checklist-items">
                <PanelHeader label="By item">
                    {data !== undefined && <Filter repos={reposOf(data.items, search.repo)} />}
                </PanelHeader>
                {data === undefined ? (
                    <PanelLoading query={query} rows={6} className="min-h-40" />
                ) : data.items.length === 0 ? (
                    <Empty size="panel">
                        no worker run of these {span} was given a checklist: each repository&apos;s is a file in{' '}
                        <Code>paths.checklists</Code>
                    </Empty>
                ) : (
                    <Items groups={itemsByRepo(data.items, search.repo)} repo={search.repo} span={span} />
                )}
            </Panel>
        </>
    )
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

/**
 * One table of every repository's items, a group of rows each, under its name: an item, the runs reminded of it, and
 * each answer's count, in `canopy checklist`'s columns. A count of none is muted, so what was answered stands out.
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
        <PanelScroll label="Checklist answers by item" className="px-3 pb-3">
            <table className="border-collapse text-sm" data-testid="checklist-table">
                <thead className={PADDED_HEAD}>
                    <tr className="text-right">
                        <th className="panel-label pb-1.5 text-left font-normal">item</th>
                        <th className={HEAD}>
                            <Hinted hint={REMINDED_HINT}>reminded</Hinted>
                        </th>
                        {ANSWER_COLUMNS.map((c) => (
                            <th key={c.key} className={HEAD}>
                                <Hinted hint={c.hint}>{c.label}</Hinted>
                            </th>
                        ))}
                    </tr>
                </thead>
                {groups.map((group, i) => (
                    <tbody key={group.repo} className="font-mono text-xs" data-testid="checklist-repo">
                        <tr>
                            <th
                                scope="rowgroup"
                                colSpan={ANSWER_COLUMNS.length + 2}
                                className={cn('pb-1 text-left font-medium text-foreground', i > 0 && 'pt-4')}
                            >
                                {group.repo}
                            </th>
                        </tr>
                        {group.items.map((item) => (
                            <tr key={item.item} className="text-right" data-testid="checklist-item">
                                <th scope="row" className="py-0.5 text-left font-normal">
                                    {/* The row's name, as the spend page's tools read: medium weight, cut to fit. */}
                                    <Clipped text={item.item} className="block max-w-lg font-sans font-medium" />
                                </th>
                                <td className="readout pl-3">{item.reminded}</td>
                                {ANSWER_COLUMNS.map((c) => (
                                    <td
                                        key={c.key}
                                        className={cn('readout pl-3', item[c.key] === 0 && 'text-muted-foreground')}
                                    >
                                        {item[c.key]}
                                    </td>
                                ))}
                            </tr>
                        ))}
                    </tbody>
                ))}
            </table>
        </PanelScroll>
    )
}
