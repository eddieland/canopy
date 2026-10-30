// The checklist page: how worker runs answered each repository's checklist, item by item, over a window of local days.
// The counts are the server's (`canopy checklist`'s, `canopy.core.checklist_answers.counts`); this lays them out.

import type { ChecklistItemCounts } from '@/api/types'
import { counted } from '@/lib/descriptions'
import { inRepos } from '@/lib/repo-filter'
import { windowName } from '@/lib/spend'

/** How many days the page opens on: a week, as `canopy checklist` counts by default. */
export const DEFAULT_CHECKLIST_DAYS = 7

/** The windows the page offers, in days, shortest first: a week, the two weeks M66's measurement reads, a month. */
export const CHECKLIST_WINDOWS: readonly number[] = [DEFAULT_CHECKLIST_DAYS, 14, 30]

/** An answer's count, as the table's columns and `canopy checklist` name it, after the runs reminded. */
export interface AnswerColumn {
    /** The field of an item's counts it reads. */
    key: 'passed' | 'fixed' | 'held' | 'not_applicable' | 'unanswered'
    /** Its head, the worker's word for the answer, as the CLI prints it. */
    label: string
    /** What it counts, on its head's hover. */
    hint: string
}

/** The answers' columns, in `canopy checklist`'s order. */
export const ANSWER_COLUMNS: readonly AnswerColumn[] = [
    { key: 'passed', label: 'pass', hint: 'The diff held to the item as it was' },
    { key: 'fixed', label: 'fixed', hint: 'The diff did not, and the run committed the fix' },
    {
        key: 'held',
        label: 'held',
        hint: 'The diff does not, and the run left it so, for a reason it gave: the reason stays on its run',
    },
    { key: 'not_applicable', label: 'n/a', hint: 'The item is about nothing the diff changed' },
    { key: 'unanswered', label: 'unanswered', hint: 'The run was given the item and its result said nothing of it' },
]

/** One repository's items, in its list's order. */
export interface RepoItems {
    /** The repository. */
    repo: string
    /** Its items' counts, in its list's order. */
    items: ChecklistItemCounts[]
}

/** The window the search's `days` names, if the page offers it; undefined for the default. */
export function checklistDays(value: unknown): number | undefined {
    return CHECKLIST_WINDOWS.find((n) => n !== DEFAULT_CHECKLIST_DAYS && (n === value || String(n) === value))
}

/**
 * The items `repo`'s filter keeps (`?repo=`), grouped by repository in the order the server sends them, each
 * repository's items in its list's order.
 */
export function itemsByRepo(items: readonly ChecklistItemCounts[], repo: string | undefined): RepoItems[] {
    const groups: RepoItems[] = []
    for (const item of items) {
        if (!inRepos(item.repo, repo)) {
            continue
        }
        const last = groups.at(-1)
        if (last?.repo === item.repo) {
            last.items.push(item)
        } else {
            groups.push({ repo: item.repo, items: [item] })
        }
    }
    return groups
}

/**
 * The page's description, the window at a glance: `8 items in 2 repositories over 7 days · 2 held`; with nothing
 * counted, that no list was answered.
 */
export function checklistLine(items: readonly ChecklistItemCounts[], days: number): string {
    const span = windowName({ days })
    if (items.length === 0) {
        return `no checklist answered over ${span}`
    }
    const repos = new Set(items.map((i) => i.repo)).size
    const held = items.reduce((sum, i) => sum + i.held, 0)
    const where = repos === 1 ? '1 repository' : `${repos} repositories`
    return `${counted(items.length, 'item')} in ${where} over ${span} · ${held} held`
}
