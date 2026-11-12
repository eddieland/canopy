import type { AgentInstructions, InstructionsAgent } from '@/api/types'

/** One of the agents a standing instructions file reaches, as the instructions page names it. */
export interface InstructionsReader {
    /** The agent, as the API names it, and its section's anchor on the page (`#worker`). */
    agent: InstructionsAgent
    /** Its name on the page. */
    label: string
    /** Which runs read its file, to finish "Read by …". */
    reaches: string
}

/** Every agent with a standing instructions file, in the order the API lists them and the page shows them. */
export const READERS: readonly InstructionsReader[] = [
    { agent: 'worker', label: 'Worker', reaches: 'every implement, resume, plan, and task run' },
    { agent: 'overseer', label: 'Overseer', reaches: 'the overseer, at every tick' },
    { agent: 'reviewer', label: 'Reviewer', reaches: 'every review' },
    { agent: 'chore', label: 'Chores', reaches: 'every chore run, after the chore’s own prompt' },
]

/** What the instructions page shows on every visit, on its title's hover. */
export const INSTRUCTIONS_HELP =
    'What each agent hears from you on every run, after its prompt’s own obligations, which come first. An agent’s ' +
    'file is the one its paths.*_instructions key names, else <agent>.md in your instructions folder, which you can ' +
    'create and delete here; a file a key names is only edited. Each change keeps the file as it was among the ' +
    'agent’s last 10 versions, in this workspace’s .canopy/. Every run started after a change reads it; one already ' +
    'going keeps the prompt it has.'

/**
 * Where an agent's file stands: `none` when it has no file, its default not there, which Create makes; `missing` when
 * the file its key names is not there, which refuses every run; `refused` when a run of it would refuse the file;
 * `set` otherwise.
 */
export type InstructionsState = 'none' | 'missing' | 'refused' | 'set'

/** Where `file` stands, for its chip, the index, and the page's line. */
export function instructionsState(file: AgentInstructions): InstructionsState {
    if (file.missing) {
        return file.source === 'default' ? 'none' : 'missing'
    }
    return file.problem === null ? 'set' : 'refused'
}

/**
 * The page's state in a line: how many agents hear standing instructions, then how many files are missing and how many
 * a run would refuse, each left out at none.
 */
export function instructionsLine(files: readonly AgentInstructions[]): string {
    const states = files.map((file) => instructionsState(file))
    const count = (state: InstructionsState) => states.filter((s) => s === state).length
    const missing = count('missing')
    const refused = count('refused')
    return [
        `${count('set')} of ${files.length} agents hear standing instructions`,
        missing > 0 ? `${missing} ${missing === 1 ? 'file' : 'files'} missing` : null,
        refused > 0 ? `${refused} ${refused === 1 ? 'file' : 'files'} a run would refuse` : null,
    ]
        .filter(Boolean)
        .join(' · ')
}

const AND = new Intl.ListFormat('en', { type: 'conjunction' })

/**
 * What leaving the page loses, as a clause the leave dialog says: `your edits to the worker and reviewer instructions
 * are not saved`, for the agents named by `labels`, in page order.
 */
export function unsavedClause(labels: readonly string[]): string {
    return `your edits to the ${AND.format(labels.map((l) => l.toLowerCase()))} instructions are not saved`
}

const ENCODER = new TextEncoder()

/**
 * How many bytes `text` takes once saved, as a run counts them: in UTF-8, with the newline the save adds to text that
 * does not end a line.
 */
export function savedBytes(text: string): number {
    const bytes = ENCODER.encode(text).length
    return text === '' || text.endsWith('\n') ? bytes : bytes + 1
}

/** A file's name, the last part of its path, as a save's line names it and its backup. */
export function fileName(path: string): string {
    return path.split('/').at(-1) ?? path
}
