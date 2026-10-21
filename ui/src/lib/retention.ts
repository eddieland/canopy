/**
 * What a page says of a file canopy's retention removed (DESIGN §26), in place of a log, prompt, or diff that is
 * gone: `removed after 30 days`. The days are the ones the operator's `[retention]` kept it, which the server reports.
 */
export function removedAfter(days: number): string {
    return `removed after ${days} ${days === 1 ? 'day' : 'days'}`
}

/** Why a page shows no output of a file that is gone: removed by retention, or gone for a reason canopy cannot tell. */
export function goneText(removedAfterDays: number | null, otherwise: string): string {
    return removedAfterDays === null ? otherwise : `${removedAfter(removedAfterDays)}, as your [retention] keeps it`
}
