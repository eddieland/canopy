import type { InstructionsAgent } from '@/api/types'

/** One of the agents a standing instructions file reaches, as the settings page names it. */
export interface InstructionsReader {
    /** The agent, as the API names it. */
    agent: InstructionsAgent
    /** Its name on the page. */
    label: string
    /** Which runs read its file, to finish "Read by …". */
    reaches: string
}

/** Every agent with a standing instructions file, in the order the API lists them. */
export const READERS: readonly InstructionsReader[] = [
    { agent: 'worker', label: 'Worker', reaches: 'every implement, resume, plan, and task run' },
    { agent: 'overseer', label: 'Overseer', reaches: 'the overseer, at every tick' },
    { agent: 'reviewer', label: 'Reviewer', reaches: 'every review' },
    { agent: 'chore', label: 'Chores', reaches: 'every chore run, after the chore’s own prompt' },
]

const ENCODER = new TextEncoder()

/**
 * How many bytes `text` takes once saved, as a run counts them: in UTF-8, with the newline the save adds to text that
 * does not end a line.
 */
export function savedBytes(text: string): number {
    const bytes = ENCODER.encode(text).length
    return text === '' || text.endsWith('\n') ? bytes : bytes + 1
}
