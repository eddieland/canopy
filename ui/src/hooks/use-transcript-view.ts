import { useState } from 'react'

import { inPage } from '@/lib/in-page'

/**
 * How a transcript is shown: By call or in order, its search, and the row last shown. A page holds it to show a row
 * from outside the panel, as the Run panel's `ended on` does; else the panel holds its own.
 */
export interface TranscriptView {
    /** Whether By call is on. */
    grouped: boolean
    /** Turns By call on or off. */
    setGrouped: (grouped: boolean) => void
    /** The search as typed. */
    typed: string
    /**
     * The search the rows are drawn for: `typed`, set in a transition after it (`inPage`), so a long transcript is
     * searched behind the field and typing never waits on it.
     */
    found: string
    /** Sets the search, and then, behind it, what the rows are drawn for. */
    setTyped: (typed: string) => void
    /** The row last shown, by its place in the log; each showing a round, so showing it again scrolls again. */
    target: { i: number; round: number } | null
    /** Shows the entry at place `i`: in order and unsearched, where every row is, opened, scrolled to, and marked. */
    show: (i: number) => void
}

/** A transcript's view, held where it is called: by the page to show a row from outside the panel. */
export function useTranscriptView(): TranscriptView {
    const [grouped, setGrouped] = useState(false)
    const [typed, setTypedNow] = useState('')
    const [found, setFound] = useState('')
    const [target, setTarget] = useState<{ i: number; round: number } | null>(null)
    const setTyped = (next: string) => {
        setTypedNow(next)
        inPage(() => setFound(next))
    }
    const show = (i: number) => {
        setGrouped(false)
        setTypedNow('')
        setFound('')
        setTarget((t) => ({ i, round: (t?.round ?? 0) + 1 }))
    }
    return { grouped, setGrouped, typed, found, setTyped, target, show }
}
