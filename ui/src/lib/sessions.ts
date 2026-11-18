import type { RuntimeSession, SessionList, SessionsWhose } from '@/api/types'

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
 * What a hit says beside its snippet, in the words `canopy sessions` prints: how many more of the session's messages
 * hold the words, and that it was indexed in part. Null for a session with neither, as one not found by its text is.
 */
export function hitNote(session: Pick<RuntimeSession, 'more_messages' | 'cut'>): string | null {
    const said: string[] = []
    if (session.more_messages > 0) {
        said.push(
            session.more_messages === 1
                ? '1 more message holds them'
                : `${session.more_messages} more messages hold them`,
        )
    }
    if (session.cut) {
        said.push('indexed in part: past its bound, words are not found')
    }
    return said.length === 0 ? null : said.join('; ')
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
