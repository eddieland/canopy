import type { CostTotal } from '@/api/types'

// Dollars to the cent, grouped by thousands (`$1,234.50`), the same in every browser's locale. It rounds what it is
// given from its shortest decimal form, so `costText` rounds to the cent first, as the CLI's `.2f` does: 0.235 is
// $0.23 in both.
const DOLLARS = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

/** A cost in dollars, as every cost in the UI is shown (`$1,234.50`), or a dash when nothing reported one. */
export function costText(cost: number | null): string {
    return cost === null ? '–' : DOLLARS.format(Number(cost.toFixed(2)))
}

/**
 * What a total cost counted, and how many of those reported no cost: `over 3 runs and 1 review, 1 unpriced`. A total
 * that counted nothing says so: `nothing has run`.
 */
export function countedText(cost: CostTotal): string {
    const counts = [counted(cost.runs, 'run'), counted(cost.reviews, 'review')].filter((c) => c !== '')
    if (counts.length === 0) {
        return 'nothing has run'
    }
    const unpriced = cost.runs + cost.reviews - cost.priced
    return `over ${counts.join(' and ')}${unpriced > 0 ? `, ${unpriced} unpriced` : ''}`
}

function counted(n: number, noun: string): string {
    if (n === 0) {
        return ''
    }
    return n === 1 ? `1 ${noun}` : `${n} ${noun}s`
}
