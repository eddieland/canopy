// The checklist page: how worker runs answered each repository's checklist, item by item, over a window of local days.
// The counts are the server's (`canopy checklist`'s, `canopy.core.checklist_answers.counts`); this lays them out. And
// one run's answers, on its page, as `canopy show run:ID` prints them; and the lists themselves, on the checklists
// page under Workspace.

import type {
    ChecklistAnswer,
    ChecklistItem,
    ChecklistItemCounts,
    ChecklistList,
    ChecklistWeek,
    ItemAnswer,
} from '@/api/types'
import type { DayBar } from '@/lib/chart'
import { counted } from '@/lib/descriptions'
import { inRepos } from '@/lib/repo-filter'
import { windowName } from '@/lib/report-window'

/**
 * How many days the page opens on: the two weeks M66's measurement reads. `canopy checklist` keeps the week every
 * report command opens on, and the guide says so.
 */
export const DEFAULT_CHECKLIST_DAYS = 14

/** The windows the page offers, in days, shortest first: a week, the two weeks the page opens on, a month. */
export const CHECKLIST_WINDOWS: readonly number[] = [7, DEFAULT_CHECKLIST_DAYS, 30]

// The verdict's thresholds. Not config: they are the guide's advice applied, not settings. Every share is of the
// answers where the item applied (pass, fixed, or held), since an n/a is the item's paths at work, not a rule kept.
//
// The answers where an item applied, none failing, before the page says it may be one to drop: under thirty, a rule
// that fails one diff in ten still shows no failure one time in twenty-five, and with ten, one time in three.
const DROP_MIN_APPLIED = 30
// The tickets whose runs held an item before it is one to argue: a ticket's runs hold it over the same diff, so they
// are one disagreement, however many runs.
const ARGUE_MIN_TICKETS = 2
// The fixes before an item is one earning its place: once may be chance.
const EARNING_MIN_FIXED = 2
// The share of the answers where it applied that an item must be held, or fixed, at least, for `argue` or `earning`:
// the low end of its 95% interval, so a few answers out of many say nothing, and the same share of few says less than
// of many.
const SHARE_FLOOR = 0.05
// The answers before the page says an item without paths is mostly n/a: under ten, mostly may be a few diffs' luck.
const NARROW_MIN_ANSWERED = 10
// The share of the runs given an item that may say nothing of it before the rest are too few to judge it by.
const MAX_UNANSWERED_SHARE = 1 / 3

/** An answer's count, as the table's columns and `canopy checklist` name it, after the runs reminded. */
export interface AnswerColumn {
    /** The field of an item's counts it reads. */
    key: 'passed' | 'fixed' | 'held' | 'not_applicable' | 'unanswered'
    /** Its head, the worker's word for the answer, as the CLI prints it. */
    label: string
    /** What it counts, on its head's hover, and in the legend's tip. */
    hint: string
    /** Its fill in the answer bar and the chart by week, written out so Tailwind finds it. */
    fill: string
}

/** The answers' columns, in `canopy checklist`'s order. */
export const ANSWER_COLUMNS: readonly AnswerColumn[] = [
    { key: 'passed', label: 'pass', hint: 'The diff held to the item as it was', fill: 'bg-answer-pass' },
    {
        key: 'fixed',
        label: 'fixed',
        hint: 'The diff did not, and the run committed the fix',
        fill: 'bg-answer-fixed',
    },
    {
        key: 'held',
        label: 'held',
        hint: 'The diff does not, and the run left it so, for a reason it gave',
        fill: 'bg-answer-held',
    },
    { key: 'not_applicable', label: 'n/a', hint: 'The item is about nothing the diff changed', fill: 'bg-answer-na' },
    {
        key: 'unanswered',
        label: 'unanswered',
        hint: 'The run was given the item and its result said nothing of it',
        fill: 'bg-answer-unanswered',
    },
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

/** The window's headline figures, over every item of every repository, as the page's tiles show them. */
export interface ChecklistFigures {
    /** How many times its runs were given an item. */
    reminded: number
    /** Of those, how many answered `held`. */
    held: number
    /** Of those, how many said nothing of it. */
    unanswered: number
}

/** The window's items given, held, and unanswered, summed over every item, as the window before's figures are. */
export function checklistFigures(items: readonly ChecklistItemCounts[]): ChecklistFigures {
    return {
        reminded: items.reduce((sum, i) => sum + i.reminded, 0),
        held: items.reduce((sum, i) => sum + i.held, 0),
        unanswered: items.reduce((sum, i) => sum + i.unanswered, 0),
    }
}

/** What the page makes of an item's answers, after its bar: the guide's advice on reading them, applied. */
export interface Verdict {
    /**
     * The word: `argue` for an item runs keep holding, `earning` for one they keep fixing, `narrow` for one without
     * paths that is mostly about other diffs, `drop?` for one that never fails where it applies, and `too few` for one
     * the answers cannot judge yet.
     */
    word: 'argue' | 'earning' | 'narrow' | 'drop?' | 'too few'
    /** Why, in its tip: what the answers were. */
    why: string
}

/**
 * What the guide would say of an item, or null for nothing to say: it fails now and then, and neither often enough to
 * argue about nor to call it earning its place. Rates, not counts, so a longer window or a busier repository says no
 * more than a shorter one, each of the answers where the item applied.
 */
export function checklistVerdict(item: ChecklistItemCounts): Verdict | null {
    if (item.reminded === 0) {
        return null
    }
    if (item.unanswered > item.reminded * MAX_UNANSWERED_SHARE) {
        return {
            word: 'too few',
            why: `${item.unanswered} of ${item.reminded} runs said nothing of it: too few answers are left to judge`,
        }
    }
    const applied = item.passed + item.fixed + item.held
    if (item.held_by >= ARGUE_MIN_TICKETS && shareAtLeast(item.held, applied) >= SHARE_FLOOR) {
        return {
            word: 'argue',
            why:
                `Held ${item.held} of ${applied} times it applied, over ${item.held_by} tickets: ` +
                'runs keep finding the rule wrong for the diff',
        }
    }
    if (item.fixed >= EARNING_MIN_FIXED && shareAtLeast(item.fixed, applied) >= SHARE_FLOOR) {
        return {
            word: 'earning',
            why: `Fixed ${item.fixed} of ${applied} times it applied: each a review comment nobody had to write`,
        }
    }
    const answered = item.reminded - item.unanswered
    if (item.paths?.length === 0 && answered >= NARROW_MIN_ANSWERED && item.not_applicable * 2 > answered) {
        return {
            word: 'narrow',
            why: `n/a ${item.not_applicable} of ${answered} answers, and it names no paths: give it the ones it is for`,
        }
    }
    if (item.fixed + item.held > 0) {
        return null
    }
    if (applied >= DROP_MIN_APPLIED) {
        return { word: 'drop?', why: `Never failed in ${applied} answers where it applied: runs pay tokens to agree` }
    }
    if (applied === 0) {
        return { word: 'too few', why: 'It has not applied to a diff yet' }
    }
    const kept = `under ${DROP_MIN_APPLIED}, a rule kept and a rule not yet met look alike`
    return { word: 'too few', why: `No failure in ${applied} answers where it applied: ${kept}` }
}

/**
 * The low end of the 95% Wilson score interval of `k` in `n`: the smallest the share may well be, given so few. Of
 * 2 in 2, about a third; of 2 in 40, about one in seventy.
 */
function shareAtLeast(k: number, n: number): number {
    if (n === 0) {
        return 0
    }
    const z = 1.96
    const p = k / n
    const spread = z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))
    return (p + (z * z) / (2 * n) - spread) / (1 + (z * z) / n)
}

/** How the By item table orders each repository's items. */
export type ChecklistSort = 'list' | 'held' | 'na' | 'unanswered'

/** The table's orders, as its sort control offers them, the list's own first. */
export const CHECKLIST_SORTS: readonly { key: ChecklistSort; label: string }[] = [
    { key: 'list', label: 'list order' },
    { key: 'held', label: 'held' },
    { key: 'na', label: 'n/a share' },
    { key: 'unanswered', label: 'unanswered' },
]

/** The order the search's `sort` names, if the page offers it; undefined for the list's own, the default. */
export function checklistSort(value: unknown): ChecklistSort | undefined {
    return CHECKLIST_SORTS.find((s) => s.key !== 'list' && s.key === value)?.key
}

/**
 * Each repository's items in `sort`'s order, the most first, ties in the list's order: by how many held it, by the
 * share of its runs that answered n/a, or by how many said nothing of it. The repositories keep theirs.
 */
export function sortGroups(groups: readonly RepoItems[], sort: ChecklistSort): RepoItems[] {
    if (sort === 'list') {
        return [...groups]
    }
    const by = (item: ChecklistItemCounts): number => {
        switch (sort) {
            case 'held': {
                return item.held
            }
            case 'na': {
                return item.reminded === 0 ? 0 : item.not_applicable / item.reminded
            }
            case 'unanswered': {
                return item.unanswered
            }
        }
    }
    return groups.map((g) => ({ ...g, items: g.items.toSorted((a, b) => by(b) - by(a)) }))
}

/** An item's key in the search's `item`, `api:newspaper-order`: a repository's name holds no colon. */
export function itemKey(item: Pick<ChecklistItemCounts, 'repo' | 'item'>): string {
    return `${item.repo}:${item.item}`
}

/** The item `key` names among those the filter keeps, or undefined for none: the whole list. */
export function pickedItem(groups: readonly RepoItems[], key: string | undefined): ChecklistItemCounts | undefined {
    return key === undefined ? undefined : groups.flatMap((g) => g.items).find((i) => itemKey(i) === key)
}

/** An item's answers in words, on its bar's hover: each answer given, in the table's order, `2 pass · 1 held`. */
export function answersWords(counts: Pick<ChecklistItemCounts, AnswerColumn['key']>): string {
    const said = ANSWER_COLUMNS.filter((c) => counts[c.key] > 0).map((c) => `${counts[c.key]} ${c.label}`)
    return said.length === 0 ? 'no answers' : said.join(' · ')
}

/** One week's answers, of one item or of the whole list. */
export interface WeekAnswers {
    /** The ISO week, `2026-W41`. */
    week: string
    /** How many runs of it were given the item, or an item of the list. */
    reminded: number
    /** How many answered `pass`. */
    passed: number
    /** How many answered `fixed`. */
    fixed: number
    /** How many answered `held`. */
    held: number
    /** How many answered `n/a`. */
    not_applicable: number
    /** How many said nothing. */
    unanswered: number
}

/**
 * The window's weeks, oldest first, each one's answers: `picked`'s alone, or with none picked, every item's the filter
 * keeps, summed.
 */
export function answersByWeek(
    weeks: readonly ChecklistWeek[],
    picked: Pick<ChecklistItemCounts, 'repo' | 'item'> | undefined,
    repo: string | undefined,
): WeekAnswers[] {
    const found = new Map<string, WeekAnswers>()
    for (const w of weeks) {
        const kept = picked === undefined ? inRepos(w.repo, repo) : itemKey(w) === itemKey(picked)
        const sum = found.get(w.week) ?? {
            week: w.week,
            reminded: 0,
            passed: 0,
            fixed: 0,
            held: 0,
            not_applicable: 0,
            unanswered: 0,
        }
        if (kept) {
            sum.reminded += w.reminded
            for (const c of ANSWER_COLUMNS) {
                sum[c.key] += w[c.key]
            }
        }
        found.set(w.week, sum)
    }
    return [...found.values()].toSorted((a, b) => a.week.localeCompare(b.week))
}

/** A week's name on the chart's axis: `W41`. */
export function weekLabel(week: string): string {
    return week.slice(week.indexOf('-') + 1)
}

/** The weeks as the chart by week draws them: a bar each, its answers stacked in the table's order, pass lowest. */
export function weekBars(weeks: readonly WeekAnswers[]): DayBar[] {
    return weeks.map((w) => ({
        key: w.week,
        label: weekLabel(w.week),
        hint: `${w.week}: ${counted(w.reminded, 'item')} given · ${answersWords(w)}`,
        total: w.reminded,
        totalText: String(w.reminded),
        segments: ANSWER_COLUMNS.map((c) => ({ key: c.key, fill: c.fill, value: w[c.key] })),
    }))
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

/** What each severity an item may name means, on its chip's hover: the reminder asks every item alike. */
export const SEVERITY_MEANING: Record<ChecklistItem['severity'], string> = {
    blocking: 'A review that asks the list would call a failing diff broken. The reminder asks it as it asks any item',
    major: 'A review that asks the list would weigh it as a major finding. The reminder asks it as it asks any item',
    minor: 'The default: a minor finding in a review that asks the list. The reminder asks it as it asks any item',
}

/**
 * What the checklists page's lists hold, its description: `2 of 3 repositories keep a list · 8 items`, then how many
 * canopy cannot use; that none is asked when `paths.checklists` is unset.
 */
export function checklistsLine(list: ChecklistList): string {
    if (list.directory === null) {
        return 'no repository is asked: paths.checklists is not set'
    }
    const kept = list.repos.filter((r) => r.error === null && r.items.length > 0)
    const items = kept.reduce((sum, r) => sum + r.items.length, 0)
    const broken = list.repos.filter((r) => r.error !== null).length
    const n = list.repos.length
    const parts = [
        `${kept.length} of ${n} ${n === 1 ? 'repository keeps' : 'repositories keep'} a list`,
        counted(items, 'item'),
        broken === 0 ? '' : `${broken} cannot be read`,
    ]
    return parts.filter((p) => p !== '').join(' · ')
}
