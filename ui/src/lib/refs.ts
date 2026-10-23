// How the UI names what canopy keeps by id (ui/DESIGN.md, "Names"): as the CLI reads a reference, `KIND:ID`, in rows,
// trails, titles, and the tab alike. A chore run has no reference of its own, so it is its chore's and its number.

/** A run, as `canopy show` reads it: `run:41`. */
export function runRef(id: number | string): string {
    return `run:${id}`
}

/** A piece of harness text: plain, or a run it names as `run:41`, with the run's id. */
export type RefPiece = { text: string; run?: undefined } | { text: string; run: number }

// A run named as the harness writes one, standing as a word of its own.
const RUN_REF = /\brun:(\d+)\b/gu

/** Split harness text around the runs it names as `run:41`, so a page can link each to its run. */
export function splitRunRefs(text: string): RefPiece[] {
    const pieces: RefPiece[] = []
    let last = 0
    for (const match of text.matchAll(RUN_REF)) {
        if (match.index > last) {
            pieces.push({ text: text.slice(last, match.index) })
        }
        pieces.push({ text: match[0], run: Number(match[1]) })
        last = match.index + match[0].length
    }
    if (last < text.length) {
        pieces.push({ text: text.slice(last) })
    }
    return pieces
}

/** A review run, as `canopy show` reads it: `review:4`. */
export function reviewRef(id: number | string): string {
    return `review:${id}`
}

/** A tick, in the same grammar: `tick:2`. */
export function tickRef(id: number | string): string {
    return `tick:${id}`
}

/** A note, proposal, or lesson, in the same grammar: `memory:3`, though `canopy memory` takes the bare id. */
export function memoryRef(id: number | string): string {
    return `memory:${id}`
}

/** A chore, as `canopy show` reads it: `chore:deps`. */
export function choreRef(name: string): string {
    return `chore:${name}`
}

/** One run of a chore: its chore, then its number, as GitHub writes an issue's: `chore:deps#2`. */
export function choreRunRef(name: string, id: number | string): string {
    return `${choreRef(name)}#${id}`
}

/** A one-off task, as `canopy show` reads it: `task:4`. */
export function taskRef(id: number | string): string {
    return `task:${id}`
}

/** One run of a task, which has no reference of its own: its task, then its number, as a chore run is: `task:4#5`. */
export function taskRunRef(task: number | string, id: number | string): string {
    return `${taskRef(task)}#${id}`
}

/** A message in a ticket's conversation, as its head line numbers it: `#5`. */
export function messageRef(id: number | string): string {
    return `#${id}`
}

/** A worktree slot, as its pool numbers it: `#3`. */
export function slotRef(name: string): string {
    return `#${name}`
}

/** A ticket's plan, as `canopy show --plans` reads it: `plan:2`. */
export function planRef(id: number | string): string {
    return `plan:${id}`
}
