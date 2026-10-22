import { useMutation } from '@tanstack/react-query'
import { Pencil, Trash2 } from 'lucide-react'
import { useId } from 'react'
import type { ReactNode, SubmitEvent } from 'react'

import { Textarea } from '@/components/input'
import { Notice } from '@/components/notice'
import { SendKeycap } from '@/components/send-keycap'
import { Button } from '@/components/ui/button'
import { MAX_DRAFT_CHARS, draftChars } from '@/lib/drafts'
import { useSendKeys } from '@/lib/send-key'
import { cn } from '@/lib/utils'

/**
 * A draft's card: text canopy holds that would post as the operator on a PR, a thread's reply or a review's comment
 * (DESIGN.md, Drafts). One tone for both: `surface`, with a `status-blocked` border while it waits on the operator.
 * `header` heads it; the rest is its text, its verbs (`DraftVerbs`), and what they did.
 */
export function DraftCardFrame({
    id,
    waiting,
    header,
    testId,
    status,
    children,
}: {
    /** Its anchor, for a link to it. */
    id?: string
    /** Whether it waits on the operator, which its border shows. */
    waiting: boolean
    /** Its header's content: a label, then what names it. */
    header: ReactNode
    /** Its test id. */
    testId: string
    /** Its status, as a data attribute, when it has one of its own. */
    status?: string
    /** Its text, verbs, and notices. */
    children: ReactNode
}) {
    return (
        <article
            id={id}
            className={cn(
                'scroll-mt-16 rounded-md border bg-surface p-3 text-sm',
                waiting && 'border-status-blocked/40',
            )}
            data-testid={testId}
            data-status={status}
        >
            <header className="flex flex-wrap items-center gap-2">{header}</header>
            {children}
        </article>
    )
}

/** The row of a draft card's verbs, under its text. */
export function DraftVerbs({ children }: { children: ReactNode }) {
    return <span className="mt-2 flex flex-wrap items-center gap-2">{children}</span>
}

/** What a draft card's verb is given: what it does, whether it may, and the CLI's command it is, shown on hover. */
interface VerbProps {
    /** Does the verb. */
    onClick: () => void
    /** Whether it is held, while another verb's write is on its way. */
    disabled: boolean
    /** The CLI's command the verb is. */
    title: string
}

/** A draft card's `Edit`: an outline `sm` button, which opens its text in `DraftForm`. */
export function EditVerb({ onClick, disabled, title }: VerbProps) {
    return (
        <Button size="sm" variant="outline" onClick={onClick} disabled={disabled} title={title}>
            <Pencil />
            Edit
        </Button>
    )
}

/** A draft card's `Drop`: a ghost `sm` button, which leaves the draft out. */
export function DropVerb({ onClick, disabled, title }: VerbProps) {
    return (
        <Button size="sm" variant="ghost" onClick={onClick} disabled={disabled} title={title}>
            <Trash2 />
            Drop
        </Button>
    )
}

/**
 * A draft's text in the operator's own words: plain text in a `Textarea`, its count against the bound a draft's text
 * is, `Save` held until `fits` and `Cancel`. The caller holds the text, so what it adds between the box and the buttons
 * (a reaction, on a thread's draft) may change it. `save` writes it, and `onSaved` hears what that returned.
 */
export function DraftForm<T>({
    label,
    text,
    onText,
    fits,
    save,
    onSaved,
    onCancel,
    children,
}: {
    /** The form's accessible name. */
    label: string
    /** The text in the box. */
    text: string
    /** Hears the text change. */
    onText: (text: string) => void
    /** Whether what the form holds may be saved, the count past the bound aside. */
    fits: boolean
    /** Writes what the form holds. */
    save: () => Promise<T>
    /** Hears what a save returned. */
    onSaved: (saved: T) => void
    /** Closes the form unsaved. */
    onCancel: () => void
    /** What goes between the box and the buttons. */
    children?: ReactNode
}) {
    const id = useId()
    const sendKeys = useSendKeys()
    const edit = useMutation({ mutationFn: save, onSuccess: (saved) => onSaved(saved) })
    const chars = draftChars(text)
    const ok = fits && chars <= MAX_DRAFT_CHARS

    function submit(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault()
        if (ok && !edit.isPending) {
            edit.mutate()
        }
    }

    return (
        <form onSubmit={submit} aria-label={label} className="mt-1.5 flex flex-col gap-2">
            <span className="flex items-baseline justify-between gap-3">
                <label className="panel-label" htmlFor={`${id}-text`}>
                    In your words
                </label>
                <span
                    className={cn(
                        'readout text-xs text-muted-foreground',
                        chars > MAX_DRAFT_CHARS && 'text-status-failed',
                    )}
                >
                    {chars} of {MAX_DRAFT_CHARS}
                </span>
            </span>
            <Textarea
                id={`${id}-text`}
                value={text}
                onChange={(event) => onText(event.target.value)}
                onKeyDown={sendKeys.onKeyDown}
                spellCheck
                // oxlint-disable-next-line jsx-a11y/no-autofocus -- the form opens on the operator's click, to type in.
                autoFocus
                className="min-h-20"
            />
            {children}
            <span className="flex flex-wrap items-center gap-2">
                <Button type="submit" size="sm" disabled={edit.isPending || !ok} aria-keyshortcuts={sendKeys.shortcut}>
                    Save
                    <SendKeycap keys={sendKeys.shortcut} />
                </Button>
                <Button type="button" size="sm" variant="ghost" onClick={onCancel} disabled={edit.isPending}>
                    Cancel
                </Button>
            </span>
            <Notice error={edit.error} />
        </form>
    )
}
