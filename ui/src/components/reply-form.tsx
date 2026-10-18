import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Command, CornerDownLeft, Send } from 'lucide-react'
import { useState } from 'react'
import type { KeyboardEvent, SubmitEvent } from 'react'

import { newSubmission, refreshChore, refreshTicket, replyChore, replyTicket } from '@/api/mutations'
import type { Replied } from '@/api/types'
import { Disclosure } from '@/components/disclosure'
import { Textarea } from '@/components/input'
import { Notice } from '@/components/notice'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { Kbd } from '@/components/ui/kbd'
import { notedText, repliedText } from '@/lib/outcomes'
import { draftKey, keepDraft, readDraft } from '@/lib/reply-draft'
import { isApple, sends, sendShortcut, useSendKey } from '@/lib/send-key'
import { cn } from '@/lib/utils'

// The operator's bound (DESIGN §22): the server refuses more, after stripping, rather than cut it.
const MAX_REPLY = 4000

const APPLE = isApple(navigator.userAgent)

/** The keys of a shortcut (`Control+Enter`) as one keycap: ⌘ and Enter as glyphs, Ctrl as its word. */
function Shortcut({ keys }: { keys: string }) {
    return (
        <Kbd aria-hidden className="ml-0.5 bg-accent-foreground/15 text-accent-foreground">
            {keys.split('+').map((key) => {
                if (key === 'Meta') {
                    return <Command key={key} />
                }
                if (key === 'Enter') {
                    return <CornerDownLeft key={key} />
                }
                return <span key={key}>Ctrl</span>
            })}
        </Kbd>
    )
}

/** What a reply goes to: a ticket, public or private, or a chore, whose next runs read it as a note (DESIGN §19). */
export type ReplyTarget = { kind: 'ticket'; key: string; isPublic: boolean } | { kind: 'chore'; name: string }

/**
 * Answers a ticket, as `canopy reply` does, or notes something to a chore, as `canopy reply chore:NAME` does. The
 * submission id is drawn when the form is rendered and kept until a reply is recorded, so sending again after an
 * uncertain result records nothing new (DESIGN §22). Until it is recorded, what is written is kept with its submission
 * id for the tab's life (`src/lib/reply-draft.ts`), so a sign-out mid-reply loses nothing. On a public ticket the
 * reply stays in canopy: it is how the operator says what to do about an untrusted reviewer's comments (D089).
 *
 * It is open where a reply is awaited: a question waiting (`waiting`), an untrusted review waiting on the go-ahead
 * (`untrusted`), any private ticket, whose workers hear the operator only here, and a chore. A public ticket with
 * nothing waiting gets a `Disclosure` instead, `Show a note for its next worker`, since a box there invites a reply
 * nothing waits on; it opens by itself once a reply is awaited, or a draft is kept, and stays open after.
 */
export function ReplyForm({
    target,
    waiting = null,
    untrusted = false,
}: {
    target: ReplyTarget
    waiting?: number | null
    untrusted?: boolean
}) {
    const client = useQueryClient()
    const sendKey = useSendKey()
    const shortcut = sendShortcut(sendKey, APPLE)
    const stored = draftKey(target.kind === 'ticket' ? `ticket:${target.key}` : `chore:${target.name}`)
    // The parent keys the form by its subject, so the draft is read once for it, on mount.
    const [draft] = useState(() => readDraft(stored))
    const [body, setBody] = useState(draft?.body ?? '')
    const [submission, setSubmission] = useState(() => draft?.submission ?? newSubmission())
    const [said, setSaid] = useState<string | null>(null)
    const awaited = target.kind === 'chore' || !target.isPublic || waiting !== null || untrusted
    const [open, setOpen] = useState(() => awaited || Boolean(draft?.body))
    // Once awaited it stays open, so the reply that ends the wait does not fold away what it said.
    if (awaited && !open) {
        setOpen(true)
    }
    const mutation = useMutation({
        mutationFn: (text: string): Promise<Replied> =>
            target.kind === 'ticket'
                ? replyTicket(target.key, text, submission)
                : replyChore(target.name, text, submission),
        onSuccess: (replied) => {
            setSaid(target.kind === 'ticket' ? repliedText(target.key, replied) : notedText(target.name, replied))
            setBody('')
            setSubmission(newSubmission())
            keepDraft(stored, { body: '', submission })
            void (target.kind === 'ticket' ? refreshTicket(client, target.key) : refreshChore(client, target.name))
        },
    })

    function submit(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault()
        if (body.trim() && !mutation.isPending) {
            mutation.mutate(body)
        }
    }

    // The key Settings names sends through the form, as the button does; any other Enter makes a new line.
    function sendOnKey(event: KeyboardEvent<HTMLTextAreaElement>) {
        const { key, shiftKey, ctrlKey, metaKey } = event
        if (!sends(sendKey, { key, shiftKey, ctrlKey, metaKey, isComposing: event.nativeEvent.isComposing })) {
            return
        }
        event.preventDefault()
        event.currentTarget.form?.requestSubmit()
    }

    const chore = target.kind === 'chore'
    // The form's noun, as its button names it.
    let label = chore ? 'Note' : 'Reply'
    if (waiting !== null) {
        label = `Reply to message ${waiting}`
    }
    let placeholder = 'The next worker reads it as an instruction.'
    if (chore) {
        placeholder = 'Its next runs read it as an instruction, a later note winning, such as a finding to leave out.'
    } else if (target.isPublic) {
        // Only while one waits does the box ask about an untrusted review; a ticket with none has nothing to say of it.
        placeholder = untrusted
            ? 'Stays in canopy, never on the ticket. Say what to do about the untrusted review.'
            : 'Stays in canopy, never on the ticket. The next worker reads it as an instruction.'
    }

    return (
        <Collapsible open={open} onOpenChange={setOpen} className="border-t">
            {!awaited && <Disclosure open={open} what="a note for its next worker" className="m-2" />}
            <CollapsibleContent asChild>
                <form
                    onSubmit={submit}
                    aria-label={chore ? 'Note' : 'Reply'}
                    className={cn('flex flex-col gap-2 p-3', !awaited && 'pt-0')}
                >
                    <label className="flex flex-col gap-1.5">
                        <span className="panel-label">{label}</span>
                        <Textarea
                            name="body"
                            value={body}
                            maxLength={MAX_REPLY}
                            onChange={(event) => {
                                setBody(event.target.value)
                                keepDraft(stored, { body: event.target.value, submission })
                            }}
                            onKeyDown={sendOnKey}
                            placeholder={placeholder}
                        />
                    </label>
                    <div className="flex items-center justify-between gap-3">
                        <Notice error={mutation.error}>{said}</Notice>
                        <span className="ml-auto readout text-xs text-muted-foreground">
                            {body.length}/{MAX_REPLY}
                        </span>
                        <Button
                            type="submit"
                            disabled={mutation.isPending || !body.trim()}
                            aria-keyshortcuts={shortcut}
                        >
                            <Send />
                            {chore ? 'Add note' : 'Reply'}
                            {shortcut && <Shortcut keys={shortcut} />}
                        </Button>
                    </div>
                </form>
            </CollapsibleContent>
        </Collapsible>
    )
}
