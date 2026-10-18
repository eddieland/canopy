import { Eraser } from 'lucide-react'
import { useId, useState } from 'react'
import type { ReactNode, SubmitEvent } from 'react'

import { Input } from '@/components/input'
import { Button } from '@/components/ui/button'

/**
 * What a Forget that cannot be undone asks first: what forgetting does, in `children`, then a field that `confirm`, a
 * ticket's key or a memory's ref, must be typed into before the button that forgets is enabled, and a ghost `Keep it`.
 * A ticket's Forget and a memory's share it, so the two read and behave alike. `name` names the form; `after` goes at
 * its foot, such as the refusal of a forget that failed.
 */
export function ForgetForm({
    confirm,
    name,
    pending,
    onForget,
    onCancel,
    after,
    children,
}: {
    /** What must be typed, exactly: a ticket's key, or a memory's ref. */
    confirm: string
    /** The form's accessible name. */
    name: string
    /** Whether a forget is in flight, which disables both buttons. */
    pending: boolean
    /** Forgets, given what was typed, once it matches. */
    onForget: (typed: string) => void
    /** Closes the form, forgetting nothing. */
    onCancel: () => void
    /** What goes at the form's foot. */
    after?: ReactNode
    /** What forgetting does, in a sentence or two. */
    children: ReactNode
}) {
    const id = useId()
    const [typed, setTyped] = useState('')
    const matches = typed === confirm

    function submit(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault()
        if (matches) {
            onForget(typed)
        }
    }

    return (
        <form
            onSubmit={submit}
            aria-label={name}
            className="flex flex-col gap-2 rounded-md border border-status-failed/40 bg-status-failed/5 p-3"
        >
            <p className="text-xs text-foreground">{children}</p>
            <label className="panel-label" htmlFor={`${id}-confirm`}>
                Type {confirm} to confirm
            </label>
            <span className="flex flex-wrap items-center gap-2">
                <Input
                    id={`${id}-confirm`}
                    value={typed}
                    onChange={(event) => setTyped(event.target.value)}
                    placeholder={confirm}
                    autoComplete="off"
                    spellCheck={false}
                    className="max-w-56 font-mono"
                />
                <Button type="submit" variant="destructive" disabled={pending || !matches}>
                    <Eraser />
                    Forget {confirm}
                </Button>
                <Button type="button" variant="ghost" onClick={onCancel} disabled={pending}>
                    Keep it
                </Button>
            </span>
            {after}
        </form>
    )
}
