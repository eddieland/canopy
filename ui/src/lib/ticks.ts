// A tick that failed or was cut short is shown in the failure color; a running one in the running color. Written out so
// Tailwind finds them.
export const TICK_TONE: Record<string, string> = {
    running: 'text-status-running',
    overseer_failed: 'text-status-failed',
    reconcile_failed: 'text-status-failed',
    abandoned: 'text-status-failed',
}

/** A tick's id from a page's path: a positive whole number, or null for anything else. */
export function tickId(param: string): number | null {
    if (!/^[1-9][0-9]{0,15}$/.test(param)) return null
    return Number(param)
}
