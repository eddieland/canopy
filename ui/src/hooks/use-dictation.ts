import { createContext, use, useEffect, useRef, useState } from 'react'

import { dictate } from '@/api/mutations'
import { speechWav } from '@/lib/wav'

/**
 * Whether the server offers dictation (`serve.dictation_cmd`), as its meta says, set by the shell. Outside one, as in a
 * unit test, it is off, so a field renders anywhere with no microphone.
 */
export const DictationContext = createContext(false)

/**
 * The longest a recording runs before it stops by itself, in seconds: under the server's 300, which a recording
 * stopped a tick of the clock late would pass.
 */
export const MAX_DICTATION_SECONDS = 290

/** Where a field's dictation is: waiting, recording the operator, or waiting on the server's text. */
export type DictationState = 'idle' | 'recording' | 'transcribing'

/** A field's dictation, from `useDictation`. */
export interface Dictation {
    /** Whether the server offers dictation at all; a field shows no microphone without it. */
    offered: boolean
    /** Why this page cannot record, such as an origin that is not secure; null when it can. */
    blocked: string | null
    /** Where it is. */
    state: DictationState
    /** Whole seconds recorded so far. */
    seconds: number
    /** What went wrong last, for `Notice`; null since the next recording started. */
    error: unknown
    /** A note that is no error, such as a recording in which nothing was heard; null otherwise. */
    note: string | null
    /** Start recording, or stop and transcribe what was recorded. */
    toggle: () => void
}

/**
 * Dictation for one field: records the operator through the browser's microphone, makes the recording the WAV the
 * server takes, and gives `onText` what the operator's command heard, for the field to put where its cursor is. A
 * recording stops by itself at `MAX_DICTATION_SECONDS`, and the microphone is let go once it stops, or when the field
 * leaves the page.
 */
export function useDictation(onText: (text: string) => void): Dictation {
    const offered = use(DictationContext)
    const [state, setState] = useState<DictationState>('idle')
    const [seconds, setSeconds] = useState(0)
    const [error, setError] = useState<unknown>(null)
    const [note, setNote] = useState<string | null>(null)
    const recorder = useRef<MediaRecorder | null>(null)
    const clock = useRef<ReturnType<typeof setInterval> | undefined>(undefined)
    const heard = useRef(onText)

    useEffect(() => {
        heard.current = onText
    })

    // A field that leaves the page while it records stops recording, and lets go of the microphone.
    useEffect(
        () => () => {
            clearInterval(clock.current)
            const going = recorder.current
            if (going !== null) {
                going.onstop = null
                going.stop()
                release(going.stream)
            }
        },
        [],
    )

    function stop() {
        clearInterval(clock.current)
        const going = recorder.current
        recorder.current = null
        if (going !== null && going.state !== 'inactive') {
            setState('transcribing')
            going.stop()
        }
    }

    async function transcribe(recorded: Blob) {
        try {
            const found = await dictate(await speechWav(recorded))
            if (found.text === '') {
                setNote('Nothing was heard in that recording.')
            } else {
                heard.current(found.text)
            }
        } catch (error_) {
            setError(error_)
        } finally {
            setState('idle')
        }
    }

    async function start() {
        setError(null)
        setNote(null)
        let stream: MediaStream
        try {
            stream = await navigator.mediaDevices.getUserMedia({
                audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
            })
        } catch (error_) {
            setError(new Error(microphoneTrouble(error_)))
            return
        }
        const made = new MediaRecorder(stream)
        const chunks: Blob[] = []
        made.ondataavailable = (event) => {
            if (event.data.size > 0) {
                chunks.push(event.data)
            }
        }
        made.onstop = () => {
            release(stream)
            void transcribe(new Blob(chunks, { type: made.mimeType }))
        }
        made.start()
        recorder.current = made
        const began = Date.now()
        setSeconds(0)
        setState('recording')
        clock.current = setInterval(() => {
            const since = (Date.now() - began) / 1000
            setSeconds(Math.floor(since))
            if (since >= MAX_DICTATION_SECONDS) {
                stop()
            }
        }, 250)
    }

    function toggle() {
        if (state === 'recording') {
            stop()
        } else if (state === 'idle') {
            void start()
        }
    }

    return { offered, blocked: offered ? blockedHere() : null, state, seconds, error, note, toggle }
}

// Browsers give the microphone only to a page on a secure origin: HTTPS, or localhost, which an SSH forward is.
function blockedHere(): string | null {
    if (!globalThis.isSecureContext) {
        return 'Dictation needs this page over HTTPS or localhost: the browser gives no microphone to plain HTTP.'
    }
    if (typeof MediaRecorder === 'undefined' || !('mediaDevices' in navigator)) {
        return 'This browser cannot record here.'
    }
    return null
}

function microphoneTrouble(failed: unknown): string {
    const name = failed instanceof DOMException ? failed.name : ''
    if (name === 'NotAllowedError' || name === 'SecurityError') {
        return 'the browser was not allowed to use the microphone: allow it in the address bar, then try again'
    }
    if (name === 'NotFoundError' || name === 'OverconstrainedError') {
        return 'no microphone was found'
    }
    return 'the microphone could not be opened'
}

function release(stream: MediaStream) {
    for (const track of stream.getTracks()) {
        track.stop()
    }
}
