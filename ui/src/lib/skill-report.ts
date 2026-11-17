// The Skills report: which skills the agents were offered and loaded, and what each one's front matter cost.
// The numbers are the server's; this lays them out.

import type { SkillsAgent, SkillsPrevious, SkillsReport, SkillsSkill, SkillsUse } from '@/api/types'
import { counted } from '@/lib/descriptions'
import { pickWindow, windowName } from '@/lib/report-window'
import type { ReportWindow } from '@/lib/report-window'
import { tokenCount } from '@/lib/transcript'

/** The window the page opens on: the week, as the health page does. */
export const DEFAULT_SKILLS_WINDOW: ReportWindow = { days: 7 }

/** The windows the page offers, shortest first, the health page's: whole local days. */
export const SKILLS_WINDOWS: readonly ReportWindow[] = [DEFAULT_SKILLS_WINDOW, { days: 30 }]

/** The window the search params name, if the page offers it; undefined for the default. */
export function skillsWindow(search: { days?: unknown }): ReportWindow | undefined {
    return pickWindow(SKILLS_WINDOWS, search)
}

/** How the skills are ordered: by what each cost, how seldom or how often it was loaded, or its name. */
export type SkillsSort = 'cost' | 'rate' | 'loads' | 'name'

/** The orders the page offers, the one it opens on first, each with its name on the toggle. */
export const SKILLS_SORTS: readonly { key: SkillsSort; label: string }[] = [
    { key: 'cost', label: 'front matter' },
    { key: 'rate', label: 'load rate' },
    { key: 'loads', label: 'loads' },
    { key: 'name', label: 'name' },
]

/** The order the search params name, if the page offers it; undefined for the one it opens on. */
export function skillsSort(search: { order?: unknown }): SkillsSort | undefined {
    const picked = SKILLS_SORTS.find((s) => s.key === search.order)?.key
    return picked === 'cost' ? undefined : picked
}

/**
 * The skills in an order (`SkillsSort`): `cost`, the most front matter sent first, then the largest a call, so a skill
 * no run is counted for still sits by its size, then the most runs offered, which is what orders them while no size
 * is on record; `rate`, the lowest load rate first, the skills never offered last;
 * `loads`, the most loads first; `name`, as the server lists them. Skills that tie keep their names' order.
 */
export function sortedSkills(skills: readonly SkillsSkill[], sort: SkillsSort = 'cost'): SkillsSkill[] {
    const figures = SORT_FIGURES[sort]
    return skills.toSorted((a, b) => {
        const [x, y] = [figures(a), figures(b)]
        const at = x.findIndex((figure, i) => figure !== y[i])
        return at === -1 ? a.name.localeCompare(b.name) : (x[at] ?? 0) - (y[at] ?? 0)
    })
}

// What each order sorts a skill by, the smallest first, each figure breaking the ties of the one before it. A skill
// with no load rate, never offered, sorts after every rate; one with no front matter on record, after every size.
const SORT_FIGURES: Record<SkillsSort, (skill: SkillsSkill) => number[]> = {
    cost: (s) => [-s.est_sent_tokens, -(s.front_matter_chars ?? -1), -s.offered],
    rate: (s) => [loadRate(s) ?? 2, -s.offered],
    loads: (s) => [-s.loads],
    name: () => [],
}

/** The runs that loaded a skill as a share of the runs offered it, 0 to 1; null for one no run was offered. */
export function loadRate(row: Pick<SkillsSkill, 'offered' | 'loaded'>): number | null {
    return row.offered === 0 ? null : row.loaded / row.offered
}

/**
 * The page's description, the window's state: `8 skills offered over 7 days · 4 never loaded · ~88.6k tokens of front
 * matter`, the cost left out while no run is counted for one, or `no skill offered over 7 days`.
 */
export function skillsLine(found: Pick<SkillsReport, 'days' | 'offered' | 'unused' | 'counted' | 'est_sent_tokens'>) {
    const over = windowName(found)
    if (found.offered === 0) {
        return `no skill offered over ${over}`
    }
    return [
        `${counted(found.offered, 'skill')} offered over ${over}`,
        found.unused === 0 ? 'each one loaded' : `${found.unused} never loaded`,
        ...(found.counted === 0 ? [] : [`~${tokenCount(found.est_sent_tokens)} tokens of front matter`]),
    ].join(' · ')
}

/** The window's headline figures, as the page's tiles show them. */
export interface SkillsFigures {
    /** The skills a run was offered. */
    offered: number
    /** Of those, the ones no run loaded. */
    unused: number
    /** The loads, of every skill canopy could name. */
    loads: number
    /** About how many tokens the skills' front matter added to the counted runs' calls; null while none is counted. */
    sent: number | null
    /** About how many it added to one model call, the counted calls' mean; null while none is counted. */
    call: number | null
}

/** The window's skills offered, those never loaded, the loads, and the front matter sent, in all and a call. */
export function skillsFigures(
    found: Pick<
        SkillsReport | SkillsPrevious,
        'offered' | 'unused' | 'loads' | 'counted' | 'est_sent_tokens' | 'est_call_tokens'
    >,
): SkillsFigures {
    return {
        offered: found.offered,
        unused: found.unused,
        loads: found.loads,
        sent: found.counted === 0 ? null : found.est_sent_tokens,
        call: found.est_call_tokens,
    }
}

/** A count of tokens' change, as every count of them is written: `1.2k`. */
export function tokensChange(size: number): string {
    return tokenCount(Math.round(size))
}

/**
 * What the front matter's cost is counted over, under the skills' table: the runs counted of those the runtime
 * answered for, and why the rest are left out; then the loads that named no skill, where there are any.
 */
export function coverageText(found: Pick<SkillsReport, 'said' | 'counted' | 'unnamed'>): string {
    const count = found.unnamed === 1 ? 'counts' : 'count'
    const unnamed =
        found.unnamed === 0
            ? ''
            : ` ${counted(found.unnamed, 'load')} named no skill canopy could read, and ${count} under none.`
    if (found.said === 0) {
        return `The runtime answered for no run, so no skill is counted as offered.${unnamed}`
    }
    if (found.counted === found.said) {
        return `Front matter is counted over each of the ${runsText(found.said)} the runtime answered for.${unnamed}`
    }
    return (
        `Front matter is counted over ${found.counted} of the ${runsText(found.said)} the runtime answered for: ` +
        "a run whose offer is from before canopy kept a description's length, or whose session is not read yet, " +
        `is left out.${unnamed}`
    )
}

/**
 * The runs the report cannot count an offer for, under the agents' table: those never asked about and those the
 * runtime could not answer for; empty when it answered for every run.
 */
export function unaskedText(agents: readonly Pick<SkillsAgent, 'unasked' | 'unanswered'>[]): string {
    const unasked = agents.reduce((sum, a) => sum + a.unasked, 0)
    const unanswered = agents.reduce((sum, a) => sum + a.unanswered, 0)
    const never = unasked === 1 ? 'was never asked what it was offered' : 'were never asked what they were offered'
    const parts = [
        ...(unasked === 0
            ? []
            : [`${runsText(unasked)} ${never}: a task's, an epic's plan, or one from before canopy asked.`]),
        ...(unanswered === 0 ? [] : [`The runtime could not answer for ${runsText(unanswered)}.`]),
    ]
    return parts.length === 0 ? '' : `${parts.join(' ')} Their loads are counted all the same.`
}

/** A count of runs in words: `1 run`, `21 runs`. */
export function runsText(n: number): string {
    return n === 1 ? '1 run' : `${n} runs`
}

/**
 * An agent's name without canopy's prefix, for a column's head, where the whole name would not fit: `worker-private`
 * for `canopy-worker-private`. An agent of the operator's own keeps its name.
 */
export function shortAgent(agent: string): string {
    return agent.startsWith(CANOPY_PREFIX) && agent.length > CANOPY_PREFIX.length
        ? agent.slice(CANOPY_PREFIX.length)
        : agent
}

// What canopy names its own agents with, before the role.
const CANOPY_PREFIX = 'canopy-'

/** One agent's use of a skill, by the agent's name; undefined for an agent that was not offered it and loaded none. */
export function agentUse(skill: Pick<SkillsSkill, 'uses'>, agent: string): SkillsUse | undefined {
    return skill.uses.find((u) => u.agent === agent)
}

/**
 * A cell of the skills by agents grid: the agent's runs that loaded the skill of its runs offered it, `1/4`; a dash
 * where no run of the agent's was offered it; and where one loaded it with no offer on record, how many did.
 */
export function cellText(use: Pick<SkillsUse, 'offered' | 'loaded' | 'unoffered'> | undefined): string {
    if (use === undefined || (use.offered === 0 && use.unoffered === 0)) {
        return '–'
    }
    return use.offered === 0 ? `${use.unoffered} loaded` : `${use.loaded}/${use.offered}`
}

/** A grid cell's bar: the share of the agent's runs offered the skill that loaded it; null where none was offered. */
export function cellBar(use: Pick<SkillsUse, 'offered' | 'loaded'> | undefined): number | null {
    return use === undefined || use.offered === 0 ? null : (use.loaded / use.offered) * 100
}

/**
 * A grid cell in words, on its tip: `canopy-reviewer: offered in 5 runs, loaded in 2 · ~656 tokens of front matter
 * sent`, with the runs that loaded it with no offer on record after; undefined for a dash.
 */
export function cellTip(use: SkillsUse | undefined): string | undefined {
    if (use === undefined || (use.offered === 0 && use.unoffered === 0)) {
        return undefined
    }
    const offered =
        use.offered === 0
            ? null
            : `offered in ${runsText(use.offered)}, loaded in ${use.loaded === 0 ? 'none' : use.loaded}`
    const unoffered = use.unoffered === 0 ? null : `loaded in ${runsText(use.unoffered)} with no offer on record`
    const sent = use.counted === 0 ? null : `~${tokenCount(use.est_sent_tokens)} tokens of front matter sent`
    return `${use.agent}: ${[offered, unoffered, sent].filter((part) => part !== null).join(' · ')}`
}

/**
 * What a skill's loads hold besides the figure, on its tip: those in runs with no offer on record, and the calls that
 * failed; undefined for neither.
 */
export function loadsTip(skill: Pick<SkillsSkill, 'unoffered' | 'failed'>): string | undefined {
    const parts = [
        ...(skill.unoffered === 0 ? [] : [`loaded in ${runsText(skill.unoffered)} with no offer on record`]),
        ...(skill.failed === 0 ? [] : [`${counted(skill.failed, 'call')} failed`]),
    ]
    return parts.length === 0 ? undefined : parts.join(' · ')
}

/**
 * What a skill's front matter's cost is counted over, on its tip: `over 6 of 11 runs offered it, 234 model calls`, or
 * why it has none.
 */
export function sentTip(skill: Pick<SkillsSkill, 'offered' | 'counted' | 'calls'>): string | undefined {
    if (skill.offered === 0) {
        return undefined
    }
    return skill.counted === 0
        ? `counted over none of the ${runsText(skill.offered)} offered it`
        : `over ${skill.counted} of ${runsText(skill.offered)} offered it, ${counted(skill.calls, 'model call')}`
}

/**
 * What stands out of an agent's runs, after its figures: that it is offered no skill, the runs never asked about or
 * not answered for, and how many of the rest its cost is counted over, where that is not all of them.
 */
export function agentNote(agent: Pick<SkillsAgent, 'said' | 'skills' | 'unasked' | 'unanswered' | 'counted'>): string {
    const parts = [
        ...(agent.said > 0 && agent.skills === 0 ? ['offered no skill'] : []),
        ...(agent.unasked === 0 ? [] : [`${agent.unasked} never asked about`]),
        ...(agent.unanswered === 0 ? [] : [`${agent.unanswered} not answered for`]),
        ...(agent.skills === 0 || agent.counted === agent.said
            ? []
            : [`cost counted over ${agent.counted} of ${agent.said}`]),
    ]
    return parts.join(' · ')
}
