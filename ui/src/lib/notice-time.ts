/** How long a notice to workers lasts (docs/design §8), in minutes, as `canopy notice --for` takes it. */

// The longest a notice lasts, in minutes: a week, the bound the server holds it to.
const MAX_MINUTES = 7 * 24 * 60

/**
 * How long a notice lasts from now, in whole minutes within the bound the server holds it to, to end at `iso`.
 * Rounded up, so it ends no sooner than `iso`.
 */
export function minutesUntil(iso: string, now: number): number {
    return clampMinutes(Math.ceil((Date.parse(iso) - now) / 60_000))
}

/** How long a notice was set for, from `since` to `until`, in whole minutes within the server's bound. */
export function minutesSetFor(since: string, until: string): number {
    return clampMinutes(Math.round((Date.parse(until) - Date.parse(since)) / 60_000))
}

/** A number of minutes as the CLI's `--for` writes it, largest units first: `90m` is `1h30m`, `1440` is `1d`. */
export function durationText(minutes: number): string {
    const days = Math.floor(minutes / 1440)
    const hours = Math.floor((minutes % 1440) / 60)
    const rest = minutes % 60
    const parts = [
        [days, 'd'],
        [hours, 'h'],
        [rest, 'm'],
    ] as const
    return (
        parts
            .filter(([n]) => n > 0)
            .map(([n, unit]) => `${n}${unit}`)
            .join('') || '0m'
    )
}

function clampMinutes(minutes: number): number {
    return Math.min(MAX_MINUTES, Math.max(1, minutes))
}
