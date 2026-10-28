import type { CostTotal } from '@/api/types'

// Dollars to the cent, grouped by thousands (`$1,234.50`), the same in every browser's locale. It rounds what it is
// given from its shortest decimal form, so `costText` hands it a cost already rounded to the cent. A cost that
// rounds to nothing reads `$0.00`, never `-$0.00`.
const DOLLARS = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', signDisplay: 'negative' })

/** A cost in dollars, as every cost in the UI is shown (`$1,234.50`), or a dash when nothing reported one. */
export function costText(cost: number | null): string {
    return cost === null ? '–' : DOLLARS.format(toCents(cost))
}

/**
 * What a total cost counted, and how many of those reported no cost: `over 3 runs and 1 review, 1 unpriced`. A total
 * that counted nothing says so: `nothing has run`.
 */
export function countedText(cost: Omit<CostTotal, 'models'>): string {
    const counts = [counted(cost.runs, 'run'), counted(cost.reviews, 'review')].filter((c) => c !== '')
    if (counts.length === 0) {
        return 'nothing has run'
    }
    const unpriced = cost.runs + cost.reviews - cost.priced
    return `over ${counts.join(' and ')}${unpriced > 0 ? `, ${unpriced} unpriced` : ''}`
}

/**
 * What part of a total cost no run's session named a model for: the total less what each model its runs' sessions
 * named cost (`cost.models`), null when nothing is left, to the cent, or no model was named.
 */
export function unattributedCost(cost: Pick<CostTotal, 'cost_usd' | 'models'>): number | null {
    if (cost.cost_usd === null || cost.models.length === 0) {
        return null
    }
    const rest = cost.models.reduce((left, m) => left - m.cost_usd, cost.cost_usd)
    return toCents(rest) > 0 ? rest : null
}

function counted(n: number, noun: string): string {
    if (n === 0) {
        return ''
    }
    return n === 1 ? `1 ${noun}` : `${n} ${noun}s`
}

// Rounded to the cent as the CLI's `.2f` rounds: from the number's exact value, a tie to even. So 0.235, stored just
// under, is $0.23, and 1.125, stored exactly, $1.12. `toFixed(2)` rounds a tie up and ICU from the shortest decimal
// form, so neither alone agrees. Twenty places of the value tell a tie from a near one: next to any cent's tie, two
// numbers lie more than 1e-20 apart.
function toCents(cost: number): number {
    const [whole = '0', fraction = ''] = Math.abs(cost).toFixed(20).split('.')
    const kept = BigInt(whole + fraction.slice(0, 2))
    const rest = fraction.slice(2)
    const up = /^50*$/u.test(rest) ? kept % 2n === 1n : rest > '5'
    return (Math.sign(cost) * Number(up ? kept + 1n : kept)) / 100
}
