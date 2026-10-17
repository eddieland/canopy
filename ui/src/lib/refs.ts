// How the UI names what canopy keeps by id (ui/DESIGN.md, "Names"): as the CLI reads a reference, `KIND:ID`, in rows,
// trails, titles, and the tab alike. A chore run has no reference of its own, so it is its chore's and its number.

/** A run, as `canopy show` reads it: `run:41`. */
export function runRef(id: number | string): string {
    return `run:${id}`
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

/** A message in a ticket's conversation, as its head line numbers it: `#5`. */
export function messageRef(id: number | string): string {
    return `#${id}`
}

/** A worktree slot, as treehouse numbers it in its pool: `#3`. */
export function slotRef(name: string): string {
    return `#${name}`
}
