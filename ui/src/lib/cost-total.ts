import type { CostTotal } from '@/api/types'

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
