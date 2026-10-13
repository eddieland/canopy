import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Command, CornerDownLeft, Send } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'

import { newSubmission, refreshChore, refreshTicket, replyChore, replyTicket } from '@/api/mutations'
import type { Replied } from '@/api/types'
import { Textarea } from '@/components/input'
import { Notice } from '@/components/notice'
import { Button } from '@/components/ui/button'
import { Kbd } from '@/components/ui/kbd'
import { notedText, repliedText } from '@/lib/outcomes'
import { isApple, sends, sendShortcut, useSendKey } from '@/lib/send-key'

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
 * uncertain result records nothing new (DESIGN §22). On a public ticket the reply stays in canopy: it is how the
 * operator says what to do about an untrusted reviewer's comments (D089).
 */
export function ReplyForm({ target, waiting = null }: { target: ReplyTarget; waiting?: number | null }) {
    const client = useQueryClient()
    const sendKey = useSendKey()
    const shortcut = sendShortcut(sendKey, APPLE)
    const [body, setBody] = useState('')
    const [submission, setSubmission] = useState(newSubmission)
    const [said, setSaid] = useState<string | null>(null)
    const mutation = useMutation({
        mutationFn: (text: string): Promise<Replied> =>
            target.kind === 'ticket'
                ? replyTicket(target.key, text, submission)
                : replyChore(target.name, text, submission),
        onSuccess: (replied) => {
            setSaid(target.kind === 'ticket' ? repliedText(target.key, replied) : notedText(target.name, replied))
            setBody('')
            setSubmission(newSubmission())
            void (target.kind === 'ticket' ? refreshTicket(client, target.key) : refreshChore(client, target.name))
        },
    })

    function submit(event: FormEvent<HTMLFormElement>) {
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
    let label = chore ? 'Your note' : 'Your reply'
    if (waiting !== null) {
        label = `Your answer to message ${waiting}`
    }
    let placeholder = 'The next worker reads it as an instruction.'
    if (chore) {
        placeholder = 'Its next runs read it as an instruction, a later note winning, such as a finding to leave out.'
    } else if (target.isPublic) {
        placeholder = 'Stays in canopy, never on the ticket. Say what to do about an untrusted review.'
    }

    return (
        <form onSubmit={submit} aria-label={chore ? 'Note' : 'Reply'} className="flex flex-col gap-2 border-t p-3">
            <label className="flex flex-col gap-1.5">
                <span className="panel-label">{label}</span>
                <Textarea
                    name="body"
                    value={body}
                    maxLength={MAX_REPLY}
                    onChange={(event) => setBody(event.target.value)}
                    onKeyDown={sendOnKey}
                    placeholder={placeholder}
                />
            </label>
            <div className="flex items-center justify-between gap-3">
                <Notice error={mutation.error}>{said}</Notice>
                <span className="ml-auto readout text-xs text-muted-foreground">
                    {body.length}/{MAX_REPLY}
                </span>
                <Button type="submit" disabled={mutation.isPending || !body.trim()} aria-keyshortcuts={shortcut}>
                    <Send />
                    {chore ? 'Add note' : 'Reply'}
                    {shortcut && <Shortcut keys={shortcut} />}
                </Button>
            </div>
        </form>
    )
}
