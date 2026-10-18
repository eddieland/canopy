/** A fixed word from the journal as a chip shows it: `worker_failed` reads `worker failed`, and a decision's
 * `attention:needs_reviewer` reads `attention: needs reviewer`. The CLI's spelling stays on hover (`Chip`'s `word`). */
export function readable(word: string): string {
    return word.replaceAll('_', ' ').replace(/^([a-z-]+):(?=\S)/u, '$1: ')
}

/** Why a PR has no ticket, wherever its ticket would show (`None`): canopy reviews it, and does no work on it. */
export const NO_TICKET = 'canopy only reviews it'

/** A run's kind as a chip shows it: a `resume` with its reasons, `resume (ci, review)`, as `canopy status` has it. */
export function runKind(run: { kind: string; reasons: readonly string[] }): string {
    return run.reasons.length > 0 ? `${run.kind} (${run.reasons.join(', ')})` : run.kind
}
