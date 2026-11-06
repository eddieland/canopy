import { useEffect, useState } from 'react'

import { storedSetting, useStoredSetting } from '@/lib/stored-setting'

/**
 * The epics whose full breakdown has had its moment in this browser (ui/DESIGN.md, "Fun"): the first time an epic's
 * page shows every entry of its breakdown filed, live or on the first visit after, its readout lights and drops a leaf,
 * once. Kept in localStorage, never in the journal: what this browser has celebrated is its own business.
 */

/**
 * Where localStorage keeps the epics, by id, newest first. Every one is kept, so none plays twice: an id is a few
 * bytes, and an epic is a large piece of work, so a lifetime's of them stays small.
 */
export const STORAGE_KEY = 'canopy-epics-filled'

/** The epics as stored, or none for anything that is not a list: each entry that is not an epic's id is dropped. */
export function parseFilled(raw: string | null): number[] {
    if (raw === null) {
        return []
    }
    let value: unknown
    try {
        value = JSON.parse(raw)
    } catch {
        return []
    }
    return Array.isArray(value)
        ? value.filter((id): id is number => Number.isSafeInteger(id) && (id as number) > 0)
        : []
}

const setting = storedSetting({ key: STORAGE_KEY, parse: parseFilled, serialize: (value) => JSON.stringify(value) })

/**
 * Whether epic `id`'s full breakdown plays its moment on this page: true from the first render that shows it `full`
 * where this browser never played it, and from then on while the page is open, so the moment plays to its end though
 * the breakdown changes under it. Once it plays the epic is recorded, so no later page plays it again. The page is
 * keyed by the epic, so a new epic starts over.
 */
export function useFilledMoment(id: number, full: boolean): boolean {
    const played = useStoredSetting(setting)
    const [playing, setPlaying] = useState(false)
    if (full && !playing && !played.includes(id)) {
        setPlaying(true)
    }
    useEffect(() => {
        const stored = setting.get()
        if (playing && !stored.includes(id)) {
            setting.set([id, ...stored])
        }
    }, [playing, id])
    return playing
}
