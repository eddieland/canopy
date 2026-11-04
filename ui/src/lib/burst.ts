/**
 * The word a cleared attention item's starburst letters (src/components/starburst.tsx, ui/DESIGN.md "Fun"): a comic's
 * sound effect, never a status word, so it says something went off and nothing about how the item ended.
 */

/** The sound effects a starburst may letter. None is a verdict: no DONE, OK, or FAIL. */
export const BURST_WORDS = [
    'KA-CHUNK!',
    'THWIP!',
    'SHAZAM!',
    'KAPOW!',
    'ZAP!',
    'WHAM!',
    'BLAM!',
    'SPROING!',
    'ZOK!',
    'BAMF!',
] as const

/** The word an item's starburst letters: picked by its id, so the same item always makes the same sound. */
export function burstWord(id: string): string {
    let hash = 0
    for (const char of id) {
        hash = (hash * 31 + (char.codePointAt(0) ?? 0)) % 2_147_483_647
    }
    return BURST_WORDS[hash % BURST_WORDS.length] ?? BURST_WORDS[0]
}
