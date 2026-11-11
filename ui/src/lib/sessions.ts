import type { RuntimeSession, SessionsWhose } from '@/api/types'

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

/** How many sessions a list shows, its subagents' among them, which sit under the session they ran for. */
export function sessionsShown(sessions: readonly RuntimeSession[]): number {
    return sessions.reduce((n, s) => n + 1 + sessionsShown(s.subagents), 0)
}
