/**
 * The wallet Settings' fun shops spend from: Sprig's hats (src/lib/hats.ts) and the Ghost's shells
 * (src/lib/shells.ts). It holds what canopy has spent over its whole life (`total_usd` from `GET /api/spend`): every
 * dollar the agent runtime reported is a dollar for the shops, less what they have sold, so it fills as canopy works
 * and never empties on its own. Nothing here spends anything real: the total is only read.
 */

/**
 * What is left to spend: the lifetime spend, in whole cents, less `spentCents`, what the shops have sold. Never below
 * zero, so a journal started afresh shows an empty wallet rather than a debt. Nothing spent yet (`null`) is nothing to
 * spend.
 */
export function balanceCents(totalUsd: number | null | undefined, spentCents: number): number {
    return Math.max(0, Math.round((totalUsd ?? 0) * 100) - spentCents)
}
