/** What a review's diff calls a file with no extension in its name, such as `Makefile` or `.gitignore`. */
export const NO_EXTENSION = 'no extension'

/** One type of file in a diff, and how many of its files are of it. */
export interface FileType {
    /** The type: the extension, lowercased, such as `.ts`, or `NO_EXTENSION`. */
    type: string
    /** How many of the diff's files are of it. */
    count: number
}

/**
 * A file's type, by its name: what follows the last dot, lowercased (`.ts` for `src/a.d.ts`), or `NO_EXTENSION` for a
 * name with no dot but at its start (`Makefile`, `.gitignore`).
 */
export function fileType(path: string): string {
    const name = path.slice(path.lastIndexOf('/') + 1)
    const dot = name.lastIndexOf('.')
    return dot <= 0 || dot === name.length - 1 ? NO_EXTENSION : name.slice(dot).toLowerCase()
}

/** The types of the files at `paths`, each with how many are of it, in order by name, those with no extension last. */
export function fileTypes(paths: Iterable<string>): FileType[] {
    const counts = new Map<string, number>()
    for (const path of paths) {
        const type = fileType(path)
        counts.set(type, (counts.get(type) ?? 0) + 1)
    }
    return [...counts]
        .map(([type, count]) => ({ type, count }))
        .toSorted((a, b) =>
            a.type === NO_EXTENSION || b.type === NO_EXTENSION
                ? Number(a.type === NO_EXTENSION) - Number(b.type === NO_EXTENSION)
                : a.type.localeCompare(b.type),
        )
}

/** What the file type filter's button says: `All file types`, `.ts only`, `2 of 4 file types`, or `No file types`. */
export function fileTypesLabel(types: readonly FileType[], hidden: ReadonlySet<string>): string {
    const shown = types.filter((t) => !hidden.has(t.type))
    if (shown.length === types.length) {
        return 'All file types'
    }
    if (shown.length === 0) {
        return 'No file types'
    }
    if (shown.length === 1 && shown[0] !== undefined) {
        return `${shown[0].type} only`
    }
    return `${shown.length} of ${types.length} file types`
}

/** What the line beside the filter says while it hides files: `1 file hidden by type`, `3 files hidden by type`. */
export function hiddenFilesText(files: number): string {
    return `${files} ${files === 1 ? 'file' : 'files'} hidden by type`
}
