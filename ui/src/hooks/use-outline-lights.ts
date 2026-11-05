import { createContext, use } from 'react'
import type { Dispatch, SetStateAction } from 'react'

import type { EpicOutline } from '@/api/types'

/** The id of an epic's outline pointed at on its page now, by hover or by focus; null while none is. */
export const LitContext = createContext<string | null>(null)

/** Point at an id of the outline, or at none. */
export const LightContext = createContext<Dispatch<SetStateAction<string | null>>>(ignore)

/** The outline the page's ids are of, whose words each id's tip says; null with no plan to read. */
export const OutlineContext = createContext<EpicOutline | null>(null)

/** The id pointed at on an epic's page now, or null: what a row lights itself for. */
export function useLit(): string | null {
    return use(LitContext)
}

/** What points at an id, or at none, for an id to call as it is hovered or focused, and left. */
export function useLight(): Dispatch<SetStateAction<string | null>> {
    return use(LightContext)
}

/** An id's words in the outline: a requirement's or a contract's text, an entry's title; null for an id it lacks. */
export function useWords(id: string): string | null {
    const outline = use(OutlineContext)
    const found = [...(outline?.requirements ?? []), ...(outline?.contracts ?? [])].find((named) => named.id === id)
    return found?.text ?? outline?.entries.find((entry) => entry.id === id)?.title ?? null
}

// Outside an epic's page nothing is lit, so pointing does nothing.
function ignore(): void {
    // Nothing to light.
}
