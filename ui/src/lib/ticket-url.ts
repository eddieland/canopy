/** Where `tracker.ticket_url` puts a ticket's key. The server checks it holds this exactly once. */
const KEY = '{key}'

/** A ticket's page in the tracker, from `tracker.ticket_url`, or undefined when that is unset. */
export function ticketUrl(template: string | null | undefined, ticketKey: string): string | undefined {
    if (!template?.includes(KEY)) return undefined
    return template.replace(KEY, encodeURIComponent(ticketKey))
}
