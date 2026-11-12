// Saving what the page made (a diagram's picture, a table's rows) as a file of the operator's: through the browser's
// download of a `blob:` URL, which the page's CSP allows, since it names no navigation (src/canopy/serve/spa.py).
// Nothing leaves the machine: the file is written by the browser, from memory.

// How long the file's URL is kept after the download starts, so a browser slow to read it still can, in milliseconds.
const KEPT_MS = 30_000

/** Saves `blob` as a file named `name`, as the browser saves a download. */
export function saveFile(blob: Blob, name: string): void {
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = name
    link.hidden = true
    document.body.append(link)
    link.click()
    link.remove()
    globalThis.setTimeout(() => URL.revokeObjectURL(url), KEPT_MS)
}

/**
 * `words` as part of a file's name: lowercase letters, digits, and hyphens alone, at most 60 characters, so it is a
 * name on every system and reads as the words it came from. Empty when nothing of them is left.
 */
export function fileWords(words: string): string {
    return (
        words
            .normalize('NFKD')
            // The accents a decomposed letter carries, so `é` is `e`.
            .replaceAll(/\p{M}/gu, '')
            .toLowerCase()
            .replaceAll(/[^a-z0-9]+/gu, '-')
            .slice(0, 60)
            .replaceAll(/^-+|-+$/gu, '')
    )
}
