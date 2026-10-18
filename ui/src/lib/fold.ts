// A count grouped by thousands (`13,029`), the same in every browser's locale.
const GROUPED = new Intl.NumberFormat('en-US')

/** `n` grouped by thousands (`13,029`), the same in every browser's locale. */
export function grouped(n: number): string {
    return GROUPED.format(n)
}

/**
 * What the button of a fold that draws `step` at a click says it does, while it holds `hidden` back: `Show 60 hidden
 * lines`, or `Show 500 of 13,029 hidden lines` past a step. `what` names what it holds, one and many
 * (`['hidden line', 'hidden lines']`). A diff's folds and a transcript's say it so (DESIGN.md).
 */
export function foldWords(hidden: number, step: number, what: readonly [string, string]): string {
    if (hidden <= step) {
        return `Show ${grouped(hidden)} ${hidden === 1 ? what[0] : what[1]}`
    }
    return `Show ${grouped(step)} of ${grouped(hidden)} ${what[1]}`
}
