// The checklist page: how worker runs answered each repository's checklist, item by item, over a window of local days.
// The counts are the server's (`canopy checklist`'s, `canopy.core.checklist_answers.counts`); this lays them out. And
// one run's answers, on its page, as `canopy show run:ID` prints them.

import type { ChecklistAnswer, ChecklistItemCounts, ItemAnswer } from '@/api/types'
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

/** What each answer means, in a run's answer's tip. */
export const ANSWER_MEANING: Readonly<Record<ItemAnswer, string>> = {
    pass: 'The diff held to the item as it was',
    fixed: 'The diff did not, and the run committed the fix',
    held: 'The diff does not, and the run left it so, for the reason under it',
    'n/a': 'The item is about nothing the diff changed',
    unanswered: 'The run was given the item and its result said nothing of it',
}

/** One repository's answers, on a run's page, in its list's order. */
export interface RepoAnswers {
    /** The repository. */
    repo: string
    /** What the run answered of each of its items, in its list's order. */
    answers: ChecklistAnswer[]
}

/** A run's answers grouped by repository, in the order the server sends them, each list's items in its order. */
export function answersByRepo(answers: readonly ChecklistAnswer[]): RepoAnswers[] {
    const groups: RepoAnswers[] = []
    for (const answer of answers) {
        const last = groups.at(-1)
        if (last?.repo === answer.repo) {
            last.answers.push(answer)
        } else {
            groups.push({ repo: answer.repo, answers: [answer] })
        }
    }
    return groups
}

/**
 * A run's answers at a glance, its checklist panel's readout: the repository when it is one, else how many, then how
 * many gave each answer there was, in `canopy checklist`'s order: `api · 2 pass · 1 fixed · 1 held`.
 */
export function answersLine(answers: readonly ChecklistAnswer[]): string {
    const repos = new Set(answers.map((a) => a.repo))
    const where = repos.size === 1 ? [...repos] : [`${repos.size} repositories`]
    const counts = ANSWER_COLUMNS.map((c) => [c.label, answers.filter((a) => a.answer === c.label).length] as const)
    return [...where, ...counts.filter(([, n]) => n > 0).map(([label, n]) => `${n} ${label}`)].join(' · ')
}
