// The skills page's words (DESIGN §13): where a skill's file is, and which of canopy's agents are offered it.

import type { Skill, SkillList, SkillSource } from '@/api/types'

/** What each place a skill's file can be means, for its chip's tip. */
export const SOURCE_MEANING: Record<SkillSource, string> = {
    canopy: 'shipped with canopy, in the snapshot of its definitions the runtime reads',
    workspace: "in the workspace's own config, under its root",
    home: 'yours, under your home: every session of yours loads it, canopy or not',
    'built-in': 'carried by the runtime itself',
    other: 'a file outside the workspace and your home',
}

// What every one of canopy's agents' names starts with.
const PREFIX = 'canopy-'

/** An agent of canopy's as the page names it: without the `canopy-` every one of them starts with. */
export function agentName(agent: string): string {
    return agent.startsWith(PREFIX) ? agent.slice(PREFIX.length) : agent
}

/** Which agents are offered `skill`, in a line: every one, none, or which, then those its rules deny it. */
export function offeredLine(skill: Skill): string {
    if (skill.denied.length === 0) {
        return skill.offered.length === 0 ? 'no agent asked' : 'offered to every agent'
    }
    const denied = skill.denied.map(agentName).join(', ')
    if (skill.offered.length === 0) {
        return `offered to no agent: denied to ${denied}`
    }
    return `offered to ${skill.offered.map(agentName).join(', ')}; denied to ${denied}`
}

/** The page's description: how many skills the runtime found, and how many of them come from you or the workspace. */
export function skillsLine(found: SkillList): string {
    const count = found.skills.length
    if (count === 0) {
        return 'no skills found'
    }
    const theirs = found.skills.filter((s) => s.source === 'home' || s.source === 'workspace').length
    const noun = count === 1 ? 'skill' : 'skills'
    return theirs === 0
        ? `${count} ${noun}, all canopy's or the runtime's`
        : `${count} ${noun}, ${theirs} of them yours`
}

/** The skills whose name or description holds `q`, ignoring case: every one when `q` is undefined. */
export function skillsMatching(skills: readonly Skill[], q: string | undefined): Skill[] {
    if (q === undefined) {
        return [...skills]
    }
    const needle = q.toLowerCase()
    return skills.filter((s) => s.name.toLowerCase().includes(needle) || s.description?.toLowerCase().includes(needle))
}

/** The longest `?q=` the skills page keeps. */
export const SKILL_QUERY_MAX = 100

/** A `?q=` as the skills page filters by it: a string cut to `SKILL_QUERY_MAX`, or undefined when it holds no word. */
export function skillQueryOf(raw: unknown): string | undefined {
    if (typeof raw !== 'string') {
        return undefined
    }
    const text = raw.slice(0, SKILL_QUERY_MAX)
    return text.trim() === '' ? undefined : text
}
