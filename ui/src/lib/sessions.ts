import type { RuntimeSession, SessionList, SessionsWhose } from '@/api/types'
import { costText } from '@/lib/cost-total'

// The server's bounds on a list (core/session_list.py), so the UI never asks for what it would answer with a 422.
/** How many sessions a list holds unless asked for more. */
export const SESSIONS_LISTED = 50
/** The most sessions a list holds. */
export const SESSIONS_MAX = 500
/** How many sessions each of the search page's panels of them holds, as it holds of each journal source. */
export const SESSIONS_PER_SEARCH = 20

/** Whose sessions a list holds, in the order the page offers them. `satisfies` fails the typecheck on a new one. */
export const SESSIONS_WHOSE = ['outside', 'canopy'] as const satisfies readonly SessionsWhose[]

/** Each list's name, as its panel's title and its filter's chip say it. */
export const WHOSE_LABEL: Record<SessionsWhose, string> = {
    outside: 'Sessions outside canopy',
    canopy: "canopy's sessions",
}

/** Each list's filter chip, in the words the CLI's `--canopy` reads. */
export const WHOSE_CHIP: Record<SessionsWhose, string> = {
    outside: 'outside canopy',
    canopy: "canopy's",
}

/** How a list holds a session's cost to an amount, in the order the page offers them. */
export const COST_OPS = ['lt', 'lte', 'gt', 'gte'] as const

/** One way a list holds a session's cost to an amount: below it, at most it, above it, or at least it. */
export type CostOp = (typeof COST_OPS)[number]

/** A bound on what each session listed cost: the page's `?cost=`, as `gte:5`. */
export interface CostBound {
    /** How a session's cost compares with the amount. */
    op: CostOp
    /** The amount, in dollars. */
    usd: number
}

/** Each comparison in words, as its button and an empty list say it. */
export const COST_WORDS: Record<CostOp, string> = {
    lt: 'less than',
    lte: 'at most',
    gt: 'more than',
    gte: 'at least',
}

/** The most characters an amount typed may have. */
export const COST_AMOUNT_MAX = 12

/**
 * An amount in dollars as typed, `5`, `0.5`, or `.5`, or undefined for anything else: the server takes no negative
 * amount, and the field no sign or exponent.
 */
export function costAmountOf(text: string): number | undefined {
    const typed = text.trim()
    if (typed.length > COST_AMOUNT_MAX || !/^(?:\d+\.?\d*|\.\d+)$/u.test(typed)) {
        return undefined
    }
    // One too small to write back without an exponent could not be read from the address again.
    const usd = Number(typed)
    return String(usd).includes('e') ? undefined : usd
}

/** A bound as the page keeps it in `?cost=`: its comparison, a colon, and the amount, `gte:5`. */
export function costBoundText(bound: CostBound): string {
    return `${bound.op}:${bound.usd}`
}

/** The bound a `?cost=` names, or undefined when it names none: a comparison the page offers, and an amount. */
export function costBoundOf(raw: unknown): CostBound | undefined {
    if (typeof raw !== 'string') {
        return undefined
    }
    const [name, amount, ...rest] = raw.split(':')
    const op = COST_OPS.find((o) => o === name)
    const usd = amount === undefined ? undefined : costAmountOf(amount)
    return op === undefined || usd === undefined || rest.length > 0 ? undefined : { op, usd }
}

/** A bound as what the sessions within it did: `cost at least $5.00`. */
export function costBoundWords(bound: CostBound): string {
    return `cost ${COST_WORDS[bound.op]} ${costText(bound.usd)}`
}

/** A session as words name it: its title, or `session ID` for one with none. */
export function sessionName(session: Pick<RuntimeSession, 'title' | 'session_id'>): string {
    return session.title ?? `session ${session.session_id}`
}

/**
 * The end of a directory a row has room for: its last two parts after `…/`, the whole when it has no more, so the
 * title beside it keeps the width. `/home/op/acme/infra` is `…/acme/infra`.
 */
export function directoryTail(directory: string): string {
    const parts = directory.split('/').filter(Boolean)
    return parts.length <= 2 ? directory : `…/${parts.slice(-2).join('/')}`
}

/** How many sessions a list shows, its subagents' among them, which sit under the session they ran for. */
export function sessionsShown(sessions: readonly RuntimeSession[]): number {
    return sessions.reduce((n, s) => n + 1 + sessionsShown(s.subagents), 0)
}

/**
 * How many more of a hit's messages hold the search's words, said after its snippet, which is the best of them. Null
 * when none does, as for a session not found by its text.
 */
export function moreMessages(more: number): string | null {
    if (more <= 0) {
        return null
    }
    return more === 1 ? '1 more message holds the words' : `${more} more messages hold the words`
}

/**
 * A reason as the end of a sentence that closes with its own period: `text` without the period it may end in, so a
 * failure's words never leave the line ending in two.
 */
export function unstopped(text: string): string {
    return text.replace(/\.+\s*$/u, '')
}

/**
 * Whether a search of the sessions' text may miss one the runtime keeps: `text` is asked for and the index cannot be
 * kept, is not built yet or still building, failed its last read, or was built under another `sessions.exclude`.
 */
export function indexBehind(list: Pick<SessionList, 'search' | 'index' | 'why_titles'>): boolean {
    if (list.why_titles !== null) {
        return true
    }
    if (list.search !== 'text') {
        return false
    }
    const { index } = list
    return index === null || !index.built || index.error !== null || !index.current
}
