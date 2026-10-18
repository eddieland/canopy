// A reply not yet sent, kept per ticket or chore in sessionStorage, so it outlives the reply form: a 401 swaps the
// whole page for the sign-in page, and signing in again brings the form back with the reply still in it. Its
// submission id is kept with it, so sending it again after an uncertain result still records nothing new
// (DESIGN §22). It lives as long as the tab and never reaches another, or until the operator signs out; without
// storage the form still works, and only forgets.

const PREFIX = 'canopy-reply:'

/** A reply as the form holds it: what is written, and the submission id it is sent with. */
export interface Draft {
    /** What the operator has written so far. */
    body: string
    /** The submission id the reply is sent with, kept until a reply is recorded. */
    submission: string
}

/** Where sessionStorage keeps the draft of a reply to `subject`, `ticket:ABC-1` or `chore:deps`. */
export function draftKey(subject: string): string {
    return `${PREFIX}${subject}`
}

/** The draft kept under `key`, or null when there is none, storage is unavailable, or what is kept is not a draft. */
export function readDraft(key: string): Draft | null {
    let raw: string | null
    try {
        raw = globalThis.sessionStorage.getItem(key)
    } catch {
        return null
    }
    return parseDraft(raw)
}

/** Keeps `draft` under `key`, or drops it once nothing is written. Without storage it is kept nowhere. */
export function keepDraft(key: string, draft: Draft): void {
    try {
        if (draft.body === '') {
            globalThis.sessionStorage.removeItem(key)
        } else {
            globalThis.sessionStorage.setItem(key, JSON.stringify(draft))
        }
    } catch {
        // Not kept, but the form still holds it while it is on the page.
    }
}

/** Drops every draft in this tab, as signing out does, so the next person to sign in at it sees none of them. */
export function dropDrafts(): void {
    try {
        const stored = Array.from({ length: globalThis.sessionStorage.length }, (_, i) =>
            globalThis.sessionStorage.key(i),
        )
        for (const key of stored) {
            if (key?.startsWith(PREFIX)) {
                globalThis.sessionStorage.removeItem(key)
            }
        }
    } catch {
        // Nothing was kept without storage.
    }
}

/** A draft as stored, or null for anything that is not one. */
export function parseDraft(raw: string | null): Draft | null {
    if (raw === null) {
        return null
    }
    let value: unknown
    try {
        value = JSON.parse(raw)
    } catch {
        return null
    }
    if (typeof value !== 'object' || value === null) {
        return null
    }
    const { body, submission } = value as { body?: unknown; submission?: unknown }
    if (typeof body !== 'string' || typeof submission !== 'string' || body === '' || submission === '') {
        return null
    }
    return { body, submission }
}
