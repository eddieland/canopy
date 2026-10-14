/**
 * A list whose rows leave with a moment's grace rather than vanish: the attention list's cleared items
 * (src/routes/attention.tsx, ui/DESIGN.md "Fun"). A row whose item is gone from the list stays where it was, marked
 * leaving, until the page lets it go once its exit has played.
 */

/** One row of the list: its item, and whether it is on its way out. */
export interface Listed<T> {
    /** The item the row shows: the latest one listed, or the last seen of one that left. */
    item: T
    /** Whether the item is gone from the list and the row is only playing its exit. */
    leaving: boolean
}

/**
 * The rows to show once the list becomes `next`: its items in their order, each row that was shown and whose item is
 * gone kept, leaving, just after the row it followed (or first, when nothing it followed stays). An item listed again
 * takes its place back from its leaving row.
 */
export function withLeaving<T extends { id: string }>(shown: readonly Listed<T>[], next: readonly T[]): Listed<T>[] {
    const staying = new Set(next.map((item) => item.id))
    // Each gone row, by the id of the last staying row above it, or '' for none.
    const after = new Map<string, Listed<T>[]>()
    let anchor = ''
    for (const row of shown) {
        if (staying.has(row.item.id)) {
            anchor = row.item.id
        } else {
            after.set(anchor, [...(after.get(anchor) ?? []), { item: row.item, leaving: true }])
        }
    }
    const rows = [...(after.get('') ?? [])]
    for (const item of next) {
        rows.push({ item, leaving: false }, ...(after.get(item.id) ?? []))
    }
    return rows
}

/** The rows without those that have played their exit. */
export function settled<T>(rows: readonly Listed<T>[]): Listed<T>[] {
    return rows.filter((row) => !row.leaving)
}
