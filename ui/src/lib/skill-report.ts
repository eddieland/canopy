// The Skills report: which skills the agents were offered and loaded, and what each one's front matter cost.
// The numbers are the server's; this lays them out.

import type { SkillsAgent, SkillsPrevious, SkillsReport, SkillsSkill, SkillsUse } from '@/api/types'
import { counted } from '@/lib/descriptions'
import { pickWindow, windowName } from '@/lib/report-window'
import type { ReportWindow } from '@/lib/report-window'
import { shareText } from '@/lib/spend'
import { tokenCount } from '@/lib/transcript'

/** The window the page opens on: the week, as the health page does. */
export const DEFAULT_SKILLS_WINDOW: ReportWindow = { days: 7 }

/** The windows the page offers, shortest first, the health page's: whole local days. */
export const SKILLS_WINDOWS: readonly ReportWindow[] = [DEFAULT_SKILLS_WINDOW, { days: 30 }]

/** The window the search params name, if the page offers it; undefined for the default. */
export function skillsWindow(search: { days?: unknown }): ReportWindow | undefined {
    return pickWindow(SKILLS_WINDOWS, search)
}

/** How the skills are ordered: by what each cost, by the least loaded first, or by the most. */
export type SkillsSort = 'cost' | 'least' | 'most'

/** The orders the page offers, the one it opens on first, each with its name on the toggle. */
export const SKILLS_SORTS: readonly { key: SkillsSort; label: string }[] = [
    { key: 'cost', label: 'front matter' },
    { key: 'least', label: 'least loaded' },
    { key: 'most', label: 'most loaded' },
]

/** The order the search params name, if the page offers it; undefined for the one it opens on. */
export function skillsSort(search: { order?: unknown }): SkillsSort | undefined {
    const picked = SKILLS_SORTS.find((s) => s.key === search.order)?.key
    return picked === 'cost' ? undefined : picked
}

/** The agent the search params name: any name, kept as text, which the page holds to the agents the window has. */
export function skillsAgent(search: { agent?: unknown }): string | undefined {
    return typeof search.agent === 'string' && search.agent !== '' ? search.agent : undefined
}

/** The agent picked, if the window has it: one it does not have reads as every agent. */
export function pickedAgent(agents: readonly SkillsAgent[], picked: string | undefined): SkillsAgent | undefined {
    return agents.find((a) => a.agent === picked)
}

/**
 * A row of the skills table: one skill's figures over every agent, or over the one picked. The same figures either
 * way, so the table's columns mean one thing whichever it shows.
 */
export type SkillRow = Pick<
    SkillsSkill,
    | 'name'
    | 'countable'
    | 'unused'
    | 'offered'
    | 'loaded'
    | 'unoffered'
    | 'loads'
    | 'failed'
    | 'est_body_tokens'
    | 'front_matter_chars'
    | 'est_call_tokens'
    | 'counted'
    | 'calls'
    | 'est_front_matter_tokens'
>

/**
 * The skills table's rows: each skill over every agent, or, with an agent picked, each skill that agent was offered
 * or loaded, by its own runs alone. A pair is unused when the agent was offered the skill and loaded it in no run of
 * its own, where a load would have been counted.
 */
export function skillRows(skills: readonly SkillsSkill[], agent: string | undefined): SkillRow[] {
    if (agent === undefined) {
        return [...skills]
    }
    return skills.flatMap((skill) => {
        const use = skill.uses.find((u) => u.agent === agent)
        return use === undefined ? [] : [pairRow(skill, use)]
    })
}

function pairRow(skill: SkillsSkill, use: SkillsUse): SkillRow {
    return {
        name: skill.name,
        countable: skill.countable,
        unused: skill.countable && use.offered > 0 && use.loads === 0,
        offered: use.offered,
        loaded: use.loaded,
        unoffered: use.unoffered,
        loads: use.loads,
        failed: use.failed,
        est_body_tokens: use.est_body_tokens,
        front_matter_chars: use.front_matter_chars,
        est_call_tokens: use.est_call_tokens,
        counted: use.counted,
        calls: use.calls,
        est_front_matter_tokens: use.est_front_matter_tokens,
    }
}

/**
 * The rows in an order (`SkillsSort`). `cost`: the most front matter first, then the largest a call, so a skill no
 * run is counted for still sits by its size, then the most runs offered, which is what orders them while no size is
 * on record. `least`: the skills never loaded first, then the lowest load rate, the most front matter first among
 * equals. `most`: the highest load rate first, the most runs offered among equals. A row with no load rate, never
 * offered or with loads canopy cannot count, sorts last in both. Rows that tie keep their names' order.
 */
export function sortedRows(rows: readonly SkillRow[], sort: SkillsSort = 'cost'): SkillRow[] {
    const figures = SORT_FIGURES[sort]
    return rows.toSorted((a, b) => {
        const [x, y] = [figures(a), figures(b)]
        const at = x.findIndex((figure, i) => figure !== y[i])
        return at === -1 ? a.name.localeCompare(b.name) : (x[at] ?? 0) - (y[at] ?? 0)
    })
}

// What each order sorts a row by, the smallest first, each figure breaking the ties of the one before it.
const SORT_FIGURES: Record<SkillsSort, (row: SkillRow) => number[]> = {
    cost: (r) => [-(r.est_front_matter_tokens ?? -1), -(r.front_matter_chars ?? -1), -r.offered],
    least: (r) => [r.unused ? 0 : 1, loadRate(r) ?? 2, -(r.est_front_matter_tokens ?? -1), -r.offered],
    most: (r) => [-(loadRate(r) ?? -1), -r.offered],
}

/**
 * The runs that loaded a skill as a share of the runs offered it, 0 to 1; null for one no run was offered, and for
 * one whose loads canopy cannot count under its name.
 */
export function loadRate(row: Pick<SkillRow, 'countable' | 'offered' | 'loaded'>): number | null {
    return row.offered === 0 || !row.countable ? null : row.loaded / row.offered
}

/**
 * A row's load rate as its cell says it: `63%`, or `<1%` for one loaded too seldom to round to 1; `never` for a skill
 * offered and loaded in no run, which a muted `0%` would bury; a dash where there is no rate to say.
 */
export function rateText(row: Pick<SkillRow, 'countable' | 'unused' | 'offered' | 'loaded'>): string {
    const rate = loadRate(row)
    if (rate === null) {
        return '–'
    }
    if (row.unused) {
        return 'never'
    }
    // A skill a run in hundreds loaded is not one none did.
    const said = shareText(rate)
    return rate > 0 && said === '0%' ? '<1%' : said
}

// The one phrase for a run nothing says what it was offered, wherever the page says it.
const NO_OFFER = 'no offer on record'

/**
 * What a row's load rate counts, on its tip: `loaded in 12 of the 19 runs offered it`, the runs that loaded it with
 * no offer on record after; or why it has no rate.
 */
export function rateTip(row: Pick<SkillRow, 'countable' | 'offered' | 'loaded' | 'unoffered'>): string {
    if (!row.countable) {
        return (
            'The runtime counts a load under a name of lowercase letters, digits, and single hyphens alone: its ' +
            'loads are among those that named no skill'
        )
    }
    const unoffered = row.unoffered === 0 ? [] : [`loaded in ${runsText(row.unoffered)} with ${NO_OFFER}`]
    const loaded = `loaded in ${row.loaded} of the ${runsText(row.offered)} offered it`
    return [row.offered === 0 ? `${NO_OFFER} names it` : loaded, ...unoffered].join(' · ')
}

/**
 * What a row's front matter is counted over, on its tip: `over 234 model calls, in 6 of 11 runs offered it`, or that
 * none of them is counted. The sum's parts, never a product: a skill's length may differ from one run to the next.
 */
export function frontMatterTip(row: Pick<SkillRow, 'offered' | 'counted' | 'calls'>): string | undefined {
    if (row.offered === 0) {
        return undefined
    }
    return row.counted === 0
        ? `none of the ${runsText(row.offered)} offered it is counted: no length on record, or no model calls on record`
        : `over ${counted(row.calls, 'model call')}, in ${row.counted} of ${runsText(row.offered)} offered it`
}

/** What a row's loads hold besides the figure, on its tip: the runs among them with no offer on record, if any. */
export function loadsTip(row: Pick<SkillRow, 'unoffered'>): string | undefined {
    if (row.unoffered === 0) {
        return undefined
    }
    const runs =
        row.unoffered === 1 ? '1 of the runs that loaded it has' : `${row.unoffered} of the runs that loaded it have`
    return `${runs} ${NO_OFFER}`
}

/**
 * The page's description, the window's state: `8 skills offered over 7 days · 4 never loaded · front matter ~88.6k
 * tokens in 8 of 19 runs offered a skill`, the coverage only where it is partial, `front matter not counted yet`
 * while no run is counted; or `no skill offered over 7 days`, with the loads of runs with no offer on record.
 */
export function skillsLine(
    found: Pick<
        SkillsReport,
        'days' | 'offered' | 'unused' | 'loads' | 'listed' | 'counted' | 'est_front_matter_tokens' | 'skills'
    >,
): string {
    const over = windowName(found)
    if (found.offered === 0) {
        const loads = found.loads === 0 ? [] : [counted(found.loads, 'load')]
        return [`no skill offered over ${over}`, ...loads].join(' · ')
    }
    return [
        `${counted(found.offered, 'skill')} offered over ${over}`,
        found.unused === 0 ? everyLoaded(found.skills) : `${found.unused} never loaded`,
        frontMatterWords(found),
    ].join(' · ')
}

// No skill is known never loaded: each was loaded, unless the loads of one the runtime cannot name are not counted.
function everyLoaded(skills: readonly Pick<SkillsSkill, 'countable' | 'offered'>[]): string {
    return skills.some((s) => !s.countable && s.offered > 0) ? 'none known never loaded' : 'each one loaded'
}

function frontMatterWords(found: Pick<SkillsReport, 'listed' | 'counted' | 'est_front_matter_tokens'>): string {
    if (found.est_front_matter_tokens === null) {
        return 'front matter not counted yet'
    }
    const sent = `front matter ~${tokenCount(found.est_front_matter_tokens)} tokens`
    return found.counted === found.listed
        ? sent
        : `${sent} in ${found.counted} of ${runsText(found.listed)} offered a skill`
}

/** The window's headline counts, as the page's tiles show them, which the window before's are compared with. */
export interface SkillsFigures {
    /** The skills a run was offered. */
    offered: number
    /** Of those, the ones no run loaded. */
    unused: number
    /** About how many tokens their front matter adds to one model call, the counted calls' mean; null with none. */
    call: number | null
}

/** A window's skills offered, those never loaded, and what their front matter adds to a model call. */
export function skillsFigures(
    found: Pick<SkillsReport | SkillsPrevious, 'offered' | 'unused' | 'est_call_tokens'>,
): SkillsFigures {
    return { offered: found.offered, unused: found.unused, call: found.est_call_tokens }
}

/** A count of tokens' change, as every count of them is written: `1.2k`. */
export function tokensChange(size: number): string {
    return tokenCount(Math.round(size))
}

/**
 * What the front matter is counted over, under the skills' table, on every visit: the runs counted of those offered
 * a skill, and why each of the rest is left out; then the loads that named no skill, where there are any.
 */
export function coverageText(
    found: Pick<SkillsReport, 'listed' | 'unsized' | 'unread' | 'counted' | 'unnamed'>,
): string {
    return [frontMatterCoverage(found), ...(found.unnamed === 0 ? [] : [unnamedText(found.unnamed)])].join(' ')
}

function frontMatterCoverage(found: Pick<SkillsReport, 'listed' | 'unsized' | 'unread' | 'counted'>): string {
    if (found.listed === 0) {
        return 'No run was offered a skill on record, so no front matter is counted.'
    }
    if (found.counted === found.listed) {
        return `Front matter is counted over each of the ${runsText(found.listed)} offered a skill.`
    }
    return (
        `Front matter is counted over ${found.counted} of the ${runsText(found.listed)} offered a skill: ` +
        `${uncounted(found).join(', ')}.`
    )
}

// The runs offered a skill that a cost is not counted over, by what each lacks.
function uncounted(found: Pick<SkillsReport, 'unsized' | 'unread'>): string[] {
    return [
        ...(found.unsized === 0 ? [] : [`${found.unsized} from before canopy kept a skill's length`]),
        ...(found.unread === 0 ? [] : [`${found.unread} with no model calls on record`]),
    ]
}

function unnamedText(unnamed: number): string {
    return unnamed === 1
        ? '1 load named no skill canopy could read: any skill here may be the one it loaded.'
        : `${unnamed} loads named no skill canopy could read: any skill here may be among them.`
}

/**
 * The runs nothing says what they were offered, under the agents' table, on every visit: how many, split into those
 * the runtime could not answer for and those it was never asked about, and where they are counted all the same.
 * Empty for a window no run started in.
 */
export function offersText(found: Pick<SkillsReport, 'runs' | 'unanswered' | 'unasked'>): string {
    const none = found.unanswered + found.unasked
    if (found.runs === 0) {
        return ''
    }
    if (none === 0) {
        return `Each of the ${runsText(found.runs)} has its offer on record.`
    }
    const why = [
        ...(found.unanswered === 0 ? [] : [`the runtime could not answer for ${found.unanswered}`]),
        ...(found.unasked === 0
            ? []
            : [`canopy never asked about ${found.unasked}, a task's, an epic's plan, or one from before it asked`]),
    ]
    return (
        `No offer on record for ${none} of ${runsText(found.runs)}: ${why.join(', and ')}. They count under the ` +
        'agent canopy ships for their kind of run, and their loads are counted.'
    )
}

/** A count of runs in words: `1 run`, `21 runs`. */
export function runsText(n: number): string {
    return n === 1 ? '1 run' : `${n} runs`
}

/**
 * The agents in the order their table lists them: the heaviest list a call first; then those offered skills whose
 * cost no run is counted for; then those known to be offered none, as the overseer is; last, those with no offer on
 * record, which nothing can be said of. Agents that tie keep the server's order.
 */
export function sortedAgents(agents: readonly SkillsAgent[]): SkillsAgent[] {
    return agents
        .map((agent, at) => ({ agent, at }))
        .toSorted((a, b) => {
            const rank = agentRank(a.agent) - agentRank(b.agent)
            const heavier = (b.agent.est_call_tokens ?? 0) - (a.agent.est_call_tokens ?? 0)
            return rank === 0 ? (heavier === 0 ? a.at - b.at : heavier) : rank
        })
        .map(({ agent }) => agent)
}

function agentRank(agent: SkillsAgent): number {
    if (agent.skills === null) {
        return 3
    }
    if (agent.skills === 0) {
        return 2
    }
    return agent.est_call_tokens === null ? 1 : 0
}

/** An agent's runs with no offer on record: those never asked about, and those the runtime could not answer for. */
export function noOffer(agent: Pick<SkillsAgent, 'unasked' | 'unanswered'>): number {
    return agent.unasked + agent.unanswered
}

/** An agent's runs with no offer on record, split by why, on the figure's tip; undefined when it has none. */
export function noOfferTip(agent: Pick<SkillsAgent, 'unasked' | 'unanswered'>): string | undefined {
    const parts = [
        ...(agent.unasked === 0 ? [] : [`canopy never asked about ${agent.unasked}`]),
        ...(agent.unanswered === 0 ? [] : [`the runtime could not answer for ${agent.unanswered}`]),
    ]
    return parts.length === 0 ? undefined : parts.join(' · ')
}

/**
 * What an agent's front matter a call is a mean over, on its tip: `over 128 model calls, in 2 of 4 runs offered a
 * skill`; that it is offered no skill; or why nothing can be said, by what its runs lack.
 */
export function agentCallTip(
    agent: Pick<SkillsAgent, 'skills' | 'listed' | 'unsized' | 'unread' | 'counted' | 'calls'>,
): string {
    if (agent.skills === null) {
        return `${NO_OFFER} for any of its runs`
    }
    if (agent.listed === 0) {
        return 'offered no skill, so its calls carry none'
    }
    if (agent.counted === 0) {
        return `none of its ${runsText(agent.listed)} offered a skill is counted: ${uncounted(agent).join(', ')}`
    }
    return (
        `over ${counted(agent.calls, 'model call')}, in ${agent.counted} of ${runsText(agent.listed)} ` +
        'offered a skill'
    )
}

/** What an agent's loads leave out, on their tip: those that named no skill; undefined when it has none. */
export function agentLoadsTip(agent: Pick<SkillsAgent, 'unnamed'>): string | undefined {
    return agent.unnamed === 0
        ? undefined
        : `and ${counted(agent.unnamed, 'load')} that named no skill: any skill of its may be among them`
}
