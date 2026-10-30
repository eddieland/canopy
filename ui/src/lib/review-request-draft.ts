// What the Review a PR dialog holds between openings (`ReviewDialog`), kept in sessionStorage: it outlives closing the
// dialog and reloading the tab, never reaches another tab, and goes once a request goes through or the operator signs
// out. Without storage the dialog still works, and only forgets on closing.

const KEY = 'canopy-review-request'

/** A review request as the form holds it before it is sent. */
export interface ReviewRequestDraft {
    /** The PR's URL, as written. */
    url: string
    /** The notes for the reviewer, as written. */
    notes: string
    /** The personas picked for this request alone, or null for those Settings prefers. */
    picked: readonly string[] | null
    /** The model picked for this request's reviews alone, `provider/model[@variant]`, or null for config's. */
    model: string | null
}

/** A draft with nothing in it, as the dialog first opens. */
export const EMPTY_DRAFT: ReviewRequestDraft = { url: '', notes: '', picked: null, model: null }

/** The draft kept in this tab, or an empty one when none is, storage is unavailable, or what is kept is not one. */
export function readReviewRequestDraft(): ReviewRequestDraft {
    let raw: string | null
    try {
        raw = globalThis.sessionStorage.getItem(KEY)
    } catch {
        return EMPTY_DRAFT
    }
    return parseReviewRequestDraft(raw) ?? EMPTY_DRAFT
}

/** Keeps `draft` in this tab, or drops it once it holds nothing. Without storage it is kept nowhere. */
export function keepReviewRequestDraft(draft: ReviewRequestDraft): void {
    try {
        if (draft.url === '' && draft.notes === '' && draft.picked === null && draft.model === null) {
            globalThis.sessionStorage.removeItem(KEY)
        } else {
            globalThis.sessionStorage.setItem(KEY, JSON.stringify(draft))
        }
    } catch {
        // Not kept, but the form still holds it while the dialog is open.
    }
}

/** Drops the draft, as a request going through or signing out does. */
export function dropReviewRequestDraft(): void {
    try {
        globalThis.sessionStorage.removeItem(KEY)
    } catch {
        // Nothing was kept without storage.
    }
}

/** A draft as stored, or null for anything that is not one. One kept before drafts held a model has none. */
export function parseReviewRequestDraft(raw: string | null): ReviewRequestDraft | null {
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
    const {
        url,
        notes,
        picked,
        model = null,
    } = value as {
        url?: unknown
        notes?: unknown
        picked?: unknown
        model?: unknown
    }
    if (typeof url !== 'string' || typeof notes !== 'string' || (model !== null && typeof model !== 'string')) {
        return null
    }
    if (picked === null) {
        return { url, notes, picked: null, model }
    }
    if (!Array.isArray(picked) || !picked.every((name) => typeof name === 'string')) {
        return null
    }
    return { url, notes, picked, model }
}
