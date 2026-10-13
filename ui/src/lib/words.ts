/** A fixed word from the journal as a chip shows it: `worker_failed` reads `worker failed`, and a decision's
 * `attention:needs_reviewer` reads `attention: needs reviewer`. The CLI's spelling stays on hover (`Chip`'s `word`). */
export function readable(word: string): string {
    return word.replaceAll('_', ' ').replace(/^([a-z-]+):(?=\S)/, '$1: ')
}
