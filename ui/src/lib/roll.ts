/** One glyph of a rolling readout: a digit rolls to its place on a strip of 0 to 9, anything else is drawn as is. */
export type RollCell =
    | { key: string; kind: 'digit'; digit: number; place: number }
    | { key: string; kind: 'glyph'; glyph: string }

/**
 * Splits a readout into cells keyed by their place from the right, so `9` becoming `10` rolls the units and adds a
 * tens digit, and `$4.20` becoming `$14.20` keeps every digit it had where it was. `place` counts digits from the
 * right, so the units settle first.
 */
export function rollCells(value: string): RollCell[] {
    // A value is digits and punctuation, whose code points are its characters.
    // oxlint-disable-next-line typescript/no-misused-spread
    const chars = [...value]
    let place = 0
    const cells: RollCell[] = []
    for (let i = chars.length - 1; i >= 0; i--) {
        const char = chars[i] ?? ''
        const fromRight = chars.length - 1 - i
        if (char >= '0' && char <= '9') {
            cells.push({ key: `${fromRight}d`, kind: 'digit', digit: Number(char), place: place++ })
        } else {
            cells.push({ key: `${fromRight}g`, kind: 'glyph', glyph: char })
        }
    }
    return cells.toReversed()
}
