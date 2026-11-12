/**
 * A short digest of `text` (FNV-1a, 32 bits): enough to tell words rewritten from words left as they were, and small
 * enough to keep beside each thing the operator marked in this browser. Not for anything that must not collide.
 */
export function digestOf(text: string): string {
    // FNV-1a's offset basis and prime, in decimal, which the formatter and the lint agree on.
    let hash = 2_166_136_261
    for (let i = 0; i < text.length; i += 1) {
        hash = Math.imul(hash ^ (text.codePointAt(i) ?? 0), 16_777_619)
    }
    return (hash >>> 0).toString(36)
}
