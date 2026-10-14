import type { TicketSummary } from '@/api/types'
import { readable } from '@/lib/words'

type Phased = Pick<TicketSummary, 'phase' | 'last_decision'>

/** A ticket's phase as the operator reads it, its journal words made readable (`ci failing`): the recorded one, else
 * what the last tick decided about it, else that no tick has seen it. The overseer records a decision for every ticket
 * it looks at, but not always a phase. `phaseWord` is the same in the CLI's spelling, for its hover. */
export function phaseLabel(ticket: Phased): string {
    return phrase(ticket, readable)
}

/** `phaseLabel` in the CLI's spelling (`ci_failing`), as `canopy status` prints it. */
export function phaseWord(ticket: Phased): string {
    return phrase(ticket, (word) => word)
}

function phrase(ticket: Phased, word: (journal: string) => string): string {
    if (ticket.phase !== null) {
        return word(ticket.phase)
    }
    if (ticket.last_decision !== null) {
        return `not recorded, last decision ${word(ticket.last_decision)}`
    }
    return 'not seen by a tick yet'
}
