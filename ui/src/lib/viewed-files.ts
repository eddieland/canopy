import type { DiffFile } from '@/api/types'
import { storedSetting, useStoredSetting } from '@/lib/stored-setting'

/**
 * The files of a diff the operator marked viewed (ui/DESIGN.md, "A review"), so a long diff is read a file at a time
 * and picked up where it was left. A mark is on a file's change, not its path: a file whose diff has changed since,
 * as a PR's does on its next push, is to be read again, and the same change shown on another page is already read.
 * Kept in localStorage, never in the journal: what this browser has read is its own business.
 */

/** Where localStorage keeps the marks, as a JSON array of them, oldest first. */
export const STORAGE_KEY = 'canopy-viewed-files'

/** How many marks are kept: the oldest go first, so the list never grows without end. */
export const MAX_VIEWED = 2000

/** A file's mark: its path and a fingerprint of its change, so a change to either is another mark. */
export function viewedMark(file: DiffFile): string {
    // FNV-1a over the change as git would print it: fast, and no secret, so a rare collision costs one unread file.
    let hash = 2_166_136_261
    for (const hunk of file.hunks) {
        for (const line of hunk.lines) {
            const text = `${line.kind}${line.text}\n`
            for (let i = 0; i < text.length; i += 1) {
                hash = Math.imul(hash ^ (text.codePointAt(i) ?? 0), 16_777_619)
            }
        }
    }
    return `${file.path}@${(hash >>> 0).toString(16)}`
}

/** The marks as stored: the strings of a JSON array, none for anything else. */
export function parseViewed(raw: string | null): string[] {
    let value: unknown
    try {
        value = JSON.parse(raw ?? '[]')
    } catch {
        return []
    }
    return Array.isArray(value) ? value.filter((mark) => typeof mark === 'string') : []
}

/** The marks with `mark` added, the newest, or removed; the oldest dropped past `MAX_VIEWED`. */
export function withViewed(marks: readonly string[], mark: string, viewed: boolean): string[] {
    const rest = marks.filter((kept) => kept !== mark)
    return viewed ? [...rest, mark].slice(-MAX_VIEWED) : rest
}

/** The marks of the files viewed. Re-renders on a change from this tab or another. */
export function useViewedFiles(): ReadonlySet<string> {
    return new Set(useStoredSetting(setting))
}

/**
 * Which of `files` are viewed, by their index, given the `marks` kept. Only a file whose path some mark names is
 * fingerprinted, so a long diff nobody has marked costs nothing to ask.
 */
export function viewedOf(files: readonly DiffFile[], marks: ReadonlySet<string>): boolean[] {
    const paths = new Set([...marks].map((mark) => mark.slice(0, mark.lastIndexOf('@'))))
    return files.map((file) => paths.has(file.path) && marks.has(viewedMark(file)))
}

/** What a diff's files amount to: `5 files`, and once any is marked, `5 files, 2 viewed`. */
export function filesSummary(viewed: readonly boolean[]): string {
    const read = viewed.filter(Boolean).length
    const count = `${viewed.length} ${viewed.length === 1 ? 'file' : 'files'}`
    return read === 0 ? count : `${count}, ${read} viewed`
}

/** Marks a file's change viewed, or not, stores it, and applies it now. */
export function setViewed(mark: string, viewed: boolean): void {
    setting.set(withViewed(setting.get(), mark, viewed))
}

const setting = storedSetting({ key: STORAGE_KEY, parse: parseViewed, serialize: JSON.stringify })
