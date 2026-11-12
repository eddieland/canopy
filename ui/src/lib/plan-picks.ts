import type { PlanDecision } from '@/lib/plan-decisions'
import { storedSetting, useStoredSetting } from '@/lib/stored-setting'
// The operator's answers to a plan's open decisions (src/lib/plan-decisions.ts) until they are sent: each a pick of an
// option other than the planner's. A plan is approved from its card as from its page, so the picks are kept where both
// read them: in this browser, in localStorage and synced across tabs, never the journal, as a plan's section marks are
// (src/lib/plan-marks.ts). They are a subject's newest plan's alone, a ticket's by its key or an epic's by its
// reference, so a new plan starts with none. A pick holds while its decision reads as it did when it was picked, by a
// digest of its words, so an edit to the plan's Decisions never leaves an answer on a question it was not given to.
import { digestOf } from '@/lib/text-digest'

/** One decision's pick, as kept. */
export interface StoredPick {
    /** The letter of the option picked, never the planner's own. */
    letter: string
    /** Its decision's digest when it was picked. */
    digest: string
}

/** The picks on a subject's plan, as kept. */
export interface SubjectPicks {
    /** The plan they answer, by its id: another plan of the subject has none. */
    plan: number
    /** When one was last made or dropped, ISO: the oldest subject past `PICKS_MAX` is dropped. */
    at: string
    /** Each decision's pick, by its number. */
    picks: Record<string, StoredPick>
}

/** Every subject's picks, by a ticket's key or an epic's reference. */
export type PlanPicks = Record<string, SubjectPicks>

/** Where localStorage keeps the picks. */
export const STORAGE_KEY = 'canopy-plan-picks'
/** How many subjects' picks are kept: those picked last. */
export const PICKS_MAX = 50

/**
 * The picks that still hold on `decisions`, the open decisions of the subject's plan `plan`, by decision number: each
 * whose decision reads as it did when it was picked and still offers the letter. A decision with none has the planner's
 * choice.
 */
export function picksOn(
    stored: SubjectPicks | undefined,
    plan: number,
    decisions: readonly PlanDecision[],
): Map<number, string> {
    const holding = new Map<number, string>()
    if (stored?.plan !== plan) {
        return holding
    }
    for (const decision of decisions) {
        const key = String(decision.number)
        const pick = Object.hasOwn(stored.picks, key) ? stored.picks[key] : undefined
        if (pick?.digest === digestOfDecision(decision) && decision.options.some((o) => o.letter === pick.letter)) {
            holding.set(decision.number, pick.letter)
        }
    }
    return holding
}

/**
 * `all` with `letter` picked for `decision` of `subject`'s plan `plan`, at `at`. The planner's own letter drops the
 * pick, since agreeing answers nothing; picks kept for another plan of the subject are dropped, as is a subject with
 * none left, and the oldest subjects past `PICKS_MAX`.
 */
export function withPick(
    all: PlanPicks,
    subject: string,
    plan: number,
    decision: PlanDecision,
    letter: string,
    at: string,
): PlanPicks {
    const before = Object.hasOwn(all, subject) ? all[subject] : undefined
    const picks = { ...(before?.plan === plan ? before.picks : undefined) }
    if (letter === decision.chosen) {
        delete picks[String(decision.number)]
    } else {
        picks[String(decision.number)] = { letter, digest: digestOfDecision(decision) }
    }
    const rest = Object.entries(all).filter(([key]) => key !== subject)
    const kept = Object.keys(picks).length > 0 ? [[subject, { plan, at, picks }] as const, ...rest] : rest
    const newest = kept.toSorted(([, a], [, b]) => b.at.localeCompare(a.at)).slice(0, PICKS_MAX)
    return Object.fromEntries(newest)
}

/** `all` without `subject`'s picks: they were sent, or their plan is decided. */
export function withoutPicks(all: PlanPicks, subject: string): PlanPicks {
    return Object.fromEntries(Object.entries(all).filter(([key]) => key !== subject))
}

/** The picks as stored, or none for anything that is not: each subject or pick that is not one is dropped. */
export function parsePicks(raw: string | null): PlanPicks {
    let value: unknown
    try {
        value = JSON.parse(raw ?? '{}')
    } catch {
        return {}
    }
    if (!isRecord(value)) {
        return {}
    }
    const all: PlanPicks = {}
    for (const [subject, entry] of Object.entries(value)) {
        if (
            isRecord(entry) &&
            typeof entry['plan'] === 'number' &&
            typeof entry['at'] === 'string' &&
            isRecord(entry['picks'])
        ) {
            const picks = Object.fromEntries(
                Object.entries(entry['picks']).filter((pair): pair is [string, StoredPick] => isPick(pair[1])),
            )
            all[subject] = { plan: entry['plan'], at: entry['at'], picks }
        }
    }
    return all
}

/**
 * The operator's picks on `decisions`, the open decisions of `subject`'s plan `plan`, by decision number (`picksOn`).
 * Re-renders on a pick from this tab or another, so a plan's card and its page show the same answers.
 */
export function usePlanPicks(
    subject: string,
    plan: number,
    decisions: readonly PlanDecision[],
): ReadonlyMap<number, string> {
    const all = useStoredSetting(setting)
    return picksOn(Object.hasOwn(all, subject) ? all[subject] : undefined, plan, decisions)
}

/** Picks `letter` for `decision` of `subject`'s plan `plan`, stores it, and applies it now (`withPick`). */
export function pickOption(subject: string, plan: number, decision: PlanDecision, letter: string): void {
    setting.set(withPick(setting.get(), subject, plan, decision, letter, new Date().toISOString()))
}

/** Drops `subject`'s picks, once they are sent or its plan is decided, and applies it now. */
export function clearPicks(subject: string): void {
    setting.set(withoutPicks(setting.get(), subject))
}

const setting = storedSetting({ key: STORAGE_KEY, parse: parsePicks, serialize: (value) => JSON.stringify(value) })

// A decision's digest: its question, its options by letter, and the planner's choice, so a pick holds only while all
// of what it answered reads the same.
function digestOfDecision(decision: PlanDecision): string {
    const options = decision.options.map((option) => `${option.letter}:${option.text}`)
    return digestOf([decision.question, decision.chosen, ...options].join('\n'))
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isPick(value: unknown): value is StoredPick {
    return isRecord(value) && typeof value['letter'] === 'string' && typeof value['digest'] === 'string'
}
