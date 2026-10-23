import type { Run } from '@/api/types'
import { storedSetting, useStoredSetting } from '@/lib/stored-setting'

/**
 * What a worker run is doing, as the rail's working rows say it under the ticket's title: a plain word for its kind
 * (`planning`, `fixing CI`), or in its place, while the run works, a quip for that phase (`appeasing CI`). A ticket
 * keeps the same quip for a phase on every render, in every tab, and gets another when it moves on to the next phase:
 * the pick is a hash of the ticket's key and the phase, not a roll of the dice. The quips are plain strings written
 * here, never journal text. They show only while the run works and Settings leaves them on, which is kept in
 * localStorage like the theme, and synced across tabs.
 */

/** A worker run's phase: its kind, or for a resume, each of the reasons it ran. */
export type RunPhase =
    | 'plan'
    | 'feedback-plan'
    | 'implement'
    | 'resume'
    | 'ci'
    | 'review'
    | 'reply'
    | 'conflict'
    | 'no_pr'
    | 'retarget'
    | 'split'
    | 'needs-plan'

/** Each phase in plain words, what the rail says whether the quips are on or off. */
export const PHASE_WORD: Record<RunPhase, string> = {
    plan: 'planning',
    'feedback-plan': 'planning a revision',
    implement: 'implementing',
    resume: 'resuming',
    ci: 'fixing CI',
    review: 'addressing review',
    reply: 'reading your reply',
    conflict: 'resolving conflicts',
    no_pr: 'opening a PR',
    retarget: 'retargeting',
    split: 'splitting',
    'needs-plan': 'triaging',
}

/**
 * Each phase's quips. A quip stands in the plain word's place, so each names its phase in a word the operator knows
 * (plan, code, CI, review, reply, conflict, PR, base), and fits the rail's line: 24 characters at most.
 */
export const QUIPS: Record<RunPhase, readonly string[]> = {
    plan: [
        'planning in pencil',
        'plotting the plan',
        'a plan is forming',
        'planning, with arrows',
        'planning with the duck',
        'drafting the grand plan',
    ],
    'feedback-plan': ['replanning, humbly', 'planning the comeback', 'plan v2, notes taken', 'replanning after notes'],
    implement: [
        'implementing furiously',
        'writing the code',
        'coding in the zone',
        'building it for real',
        'laying down code',
        'making the code work',
    ],
    resume: ['resuming, where was I', 'resuming, back at it', 'resuming the thread'],
    ci: [
        'appeasing CI',
        'reading red CI logs',
        'fixing CI, blaming cache',
        'coaxing CI to green',
        'bribing the CI runner',
    ],
    review: ['addressing review', 'review, nit by nit', 'revising per review', 'eating review feedback'],
    reply: ['reading your reply', 'your reply, all ears', 'acting on your reply'],
    conflict: ['resolving conflicts', 'untangling conflicts', 'conflict diplomacy', 'conflicts: <<<<<<< HEAD'],
    no_pr: ['opening the PR', 'naming the PR', 'filling the PR template', 'PR title, take three'],
    retarget: ['retargeting the base', 'new base, who dis', 'retargeting gently'],
    split: ['splitting it up', 'splitting the cake'],
    'needs-plan': ['triaging, squinting', 'triaging, sizing it up'],
}

// A retired kind reads as the phase that replaced it.
const KIND_PHASE: Record<string, RunPhase> = {
    plan: 'plan',
    'feedback-plan': 'feedback-plan',
    implement: 'implement',
    resume: 'resume',
    'fix-ci': 'ci',
    split: 'split',
    'needs-plan': 'needs-plan',
}

const REASON_PHASE: Record<string, RunPhase> = {
    ci: 'ci',
    review: 'review',
    reply: 'reply',
    conflict: 'conflict',
    no_pr: 'no_pr',
    retarget: 'retarget',
}

/** What a run is doing: its phase in plain words, and that phase's quip for its ticket. */
export interface Doing {
    /** The phase in plain words, a resume's reasons joined: `fixing CI, addressing review`. */
    word: string
    /**
     * The quip this ticket gets for this phase, `appeasing CI`, and for a resume with more reasons, how many more:
     * `appeasing CI +1`. Null for a kind canopy has no words for.
     */
    quip: string | null
}

/**
 * What `run` is doing. A resume reads as its reasons, each in its words, and draws its quip from the first; a kind
 * canopy does not know reads as itself, with no quip.
 */
export function runPhase(run: Pick<Run, 'ticket_key' | 'kind' | 'reasons'>): Doing {
    const phases = phasesOf(run)
    const [first] = phases
    if (first === undefined) {
        return { word: run.kind, quip: null }
    }
    const quips = QUIPS[first]
    const quip = quips[hash(`${run.ticket_key}:${phases.join('+')}`) % quips.length] ?? null
    const more = phases.length > 1 && quip !== null ? ` +${phases.length - 1}` : ''
    return { word: phases.map((phase) => PHASE_WORD[phase]).join(', '), quip: quip === null ? null : quip + more }
}

function phasesOf(run: Pick<Run, 'kind' | 'reasons'>): RunPhase[] {
    const kind = KIND_PHASE[run.kind]
    if (kind !== 'resume') {
        return kind === undefined ? [] : [kind]
    }
    const reasons = run.reasons.flatMap((reason) => REASON_PHASE[reason] ?? [])
    return reasons.length > 0 ? reasons : ['resume']
}

// FNV-1a, 32 bits (its offset basis and prime): the same string picks the same quip in every tab and every release.
function hash(text: string): number {
    let h = 2_166_136_261
    for (const char of text) {
        h ^= char.codePointAt(0) ?? 0
        h = Math.imul(h, 16_777_619) >>> 0
    }
    return h
}

/** Whether the rail's working rows say a run's phase with a quip. */
export type QuipsSetting = 'on' | 'off'

/** Where localStorage keeps the setting. */
export const STORAGE_KEY = 'canopy-quips'
/** The setting until the operator turns the quips off: on. */
export const DEFAULT: QuipsSetting = 'on'

/** The setting as stored, or the default for anything it does not recognize. */
export function parseQuips(raw: string | null): QuipsSetting {
    return raw === 'on' || raw === 'off' ? raw : DEFAULT
}

const setting = storedSetting({ key: STORAGE_KEY, parse: parseQuips, serialize: (value: QuipsSetting) => value })

/** Whether the quips show. Re-renders on a change from this tab or another. */
export function useQuips(): QuipsSetting {
    return useStoredSetting(setting)
}

/** Stores the setting and applies it now. */
export function setQuips(next: QuipsSetting): void {
    setting.set(next)
}
