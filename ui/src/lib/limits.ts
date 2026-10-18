import type { Limit } from '@/api/types'
import { pullRequestLabel } from '@/lib/pull-request-label'

// The limits `canopy grant` raises (DESIGN §22): a unit's runs of one kind, or a PR's review runs.

/** The limits a ticket or PR is stuck at: its runs of the kind have reached the most it may have. */
export function stuck(limits: readonly Limit[]): Limit[] {
    return limits.filter((limit) => limit.runs >= limit.limit)
}

/**
 * What a limit counts, in a few words: `resume in web`, or `reviews of acme/web#88`, the PR named as anywhere, but on
 * its own page (`ownPr`), where it is the title and the limit is just `reviews`.
 */
export function limitLabel(limit: Limit, ownPr?: string): string {
    if (limit.kind !== 'review') {
        return limit.repo === null ? limit.kind : `${limit.kind} in ${limit.repo}`
    }
    return limit.pr_url === null || limit.pr_url === ownPr ? 'reviews' : `reviews of ${pullRequestLabel(limit.pr_url)}`
}

/** A limit's runs against it, and the runs granted past the policy's: `2 of 2 runs`, `3 of 3 runs, 1 granted`. */
export function limitCount(limit: Limit): string {
    const granted = limit.granted > 0 ? `, ${limit.granted} granted` : ''
    return `${limit.runs} of ${limit.limit} runs${granted}`
}
