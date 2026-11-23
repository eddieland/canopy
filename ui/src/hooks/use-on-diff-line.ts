import { createContext, use } from 'react'

/**
 * Whether what is drawn sits in a diff, under the line it is about (ui/DESIGN.md, "A review"), set by the diff's row
 * for its cards. There a card is the row itself, with no frame of its own, and does not say again where it is: the
 * file's header and the line above it do. Anywhere else, as under a file's header or in a list, it is off.
 */
export const OnDiffLineContext = createContext(false)

/** Whether the card that asks is drawn under the diff line it is about. */
export function useOnDiffLine(): boolean {
    return use(OnDiffLineContext)
}

/**
 * The frame of a card on `surface-raised`: under its diff line, a band of the row, edge to edge, a hairline between
 * it and the card before it; anywhere else a box of its own.
 */
export function cardFrame(onLine: boolean): string {
    return onLine ? 'border-t px-3 py-2.5 first:border-t-0' : 'rounded-md border p-3'
}
