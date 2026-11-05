import { createContext, use } from 'react'
import type { Dispatch } from 'react'

import type { EpicOutline } from '@/api/types'

/** How an id is pointed at: by the mouse, or by the keyboard's focus. */
export type Pointing = 'hover' | 'focus'

/** The ids of an epic's outline pointed at on its page now, each way; null where none is. */
export interface Pointed {
    /** The id under the mouse. */
    hover: string | null
    /** The id that holds the focus. */
    focus: string | null
}

/** One id pointed at one way, or one no longer pointed at that way. */
export interface PointAt {
    /** Which way it is pointed at. */
    by: Pointing
    /** The id. */
    id: string
    /** Whether it is now pointed at, or left. */
    on: boolean
}

/**
 * What pointing does to what is pointed at: an id pointed at one way replaces what that way pointed at, and leaving it
 * clears that way alone, and only while it still points at that id, so the mouse leaving one id never puts out the one
 * the focus is on, nor a blur the one under the mouse.
 */
export function point(pointed: Pointed, { by, id, on }: PointAt): Pointed {
    if (on) {
        return { ...pointed, [by]: id }
    }
    return pointed[by] === id ? { ...pointed, [by]: null } : pointed
}

/** The id lit on an epic's page now: the one under the mouse, else the one with the focus, else none. */
export function litOf(pointed: Pointed): string | null {
    return pointed.hover ?? pointed.focus
}

/** The id of an epic's outline lit on its page now; null while none is. */
export const LitContext = createContext<string | null>(null)

/** Point at an id of the outline one way, or leave it. */
export const PointContext = createContext<Dispatch<PointAt>>(ignore)

/** The outline the page's ids are of, whose words each id's tip says; null with no plan to read. */
export const OutlineContext = createContext<EpicOutline | null>(null)

/** The id lit on an epic's page now, or null: what a row lights itself for. */
export function useLit(): string | null {
    return use(LitContext)
}

/** What points at an id, or leaves it, for an id to call as it is hovered or focused, and left. */
export function usePoint(): Dispatch<PointAt> {
    return use(PointContext)
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
