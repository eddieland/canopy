// A diagram's name, read from its Mermaid source alone, without mermaid: what its picture is called in a plan or the
// guide, for a screen reader and in its caption.

/**
 * A diagram's name, from its source's `accTitle:` line: the picture's alternative text and its caption, since an image
 * says nothing to a screen reader on its own. Undefined when it has none.
 */
export function diagramTitle(lines: readonly string[]): string | undefined {
    for (const line of lines) {
        const title = /^\s*accTitle\s*:\s*(?<title>.+?)\s*$/u.exec(line)?.groups?.['title']
        if (title !== undefined) {
            return title
        }
    }
    return undefined
}
