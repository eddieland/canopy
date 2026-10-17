// What a page says when it could not read its data (ui/DESIGN.md, "Primitives", `PanelLoading`): the server's own
// words when it answered, else that canopy did not answer, which almost always means the loop that serves it stopped.

import { ApiError } from '@/api/client'

/**
 * Why a read failed, as a sentence: `could not read it: the server answered 500: database is locked`, or, when no
 * answer came at all (a network error, an aborted fetch), that canopy did not answer, and what serves it.
 */
export function readFailure(error: unknown): string {
    if (error instanceof ApiError) {
        // A body with no words of its own says only its status, which the sentence says already.
        const said = error.message === `request failed with status ${error.status}` ? '' : `: ${error.message}`
        return `could not read it: the server answered ${error.status}${said}`
    }
    return 'could not read it: canopy did not answer. `canopy loop` serves this page; is it running?'
}
