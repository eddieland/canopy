import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Send } from 'lucide-react'
import { useState } from 'react'
import type { SubmitEvent } from 'react'

import { newSubmission, refreshChore, refreshTicket, replyChore, replyTicket } from '@/api/mutations'
import type { Replied } from '@/api/types'
import { Textarea } from '@/components/input'
import { Notice } from '@/components/notice'
import { SendKeycap } from '@/components/send-keycap'
import { Button } from '@/components/ui/button'
import { notedText, repliedText } from '@/lib/outcomes'
import { draftKey, keepDraft, readDraft } from '@/lib/reply-draft'
import { useSendKeys } from '@/lib/send-key'

// The operator's bound (DESIGN §22): the server refuses more, after stripping, rather than cut it.
const MAX_REPLY = 4000

/**
 * What a reply goes to: a ticket, public or private, or a chore, whose next runs read it as a note (DESIGN §19), and
 * which may have none yet (`noted` false), so its runs follow its prompt file alone.
 */
export type ReplyTarget =
    | { kind: 'ticket'; key: string; isPublic: boolean }
    | { kind: 'chore'; name: string; noted: boolean }

/**
 * Answers a ticket, as `canopy reply` does, or notes something to a chore, as `canopy reply chore:NAME` does. The
 * submission id is drawn when the form is rendered and kept until a reply is recorded, so sending again after an
 * uncertain result records nothing new (DESIGN §22). Until it is recorded, what is written is kept with its submission
 * id for the tab's life (`src/lib/reply-draft.ts`), so a sign-out mid-reply loses nothing. On a public ticket the
 * reply stays in canopy: it is how the operator says what to do about an untrusted reviewer's comments (D089).
 *
 * It is always open, on any ticket and any chore, so a note for the next worker is never a click away; what it is
 * for is said by its label and placeholder: the message it answers (`waiting`), an untrusted review waiting on the
 * go-ahead (`untrusted`), or where a reply on a public ticket goes.
 *
 * `onReplied` hears each reply recorded, after the form has said what it did, with that line: the attention page moves
 * on to the next item that waits on the operator.
 */
export function ReplyForm({
    target,
    waiting = null,
    untrusted = false,
    onReplied,
}: {
    target: ReplyTarget
    waiting?: number | null
    untrusted?: boolean
    onReplied?: (replied: Replied, said: string) => void
}) {
    const client = useQueryClient()
    const sendKeys = useSendKeys()
    const stored = draftKey(target.kind === 'ticket' ? `ticket:${target.key}` : `chore:${target.name}`)
    // The parent keys the form by its subject, so the draft is read once for it, on mount.
    const [draft] = useState(() => readDraft(stored))
    const [body, setBody] = useState(draft?.body ?? '')
    const [submission, setSubmission] = useState(() => draft?.submission ?? newSubmission())
    const [said, setSaid] = useState<string | null>(null)
    const mutation = useMutation({
        mutationFn: (text: string): Promise<Replied> =>
            target.kind === 'ticket'
                ? replyTicket(target.key, text, submission)
                : replyChore(target.name, text, submission),
        onSuccess: (replied) => {
            const line = target.kind === 'ticket' ? repliedText(target.key, replied) : notedText(target.name, replied)
            setSaid(line)
            setBody('')
            setSubmission(newSubmission())
            keepDraft(stored, { body: '', submission })
            void (target.kind === 'ticket' ? refreshTicket(client, target.key) : refreshChore(client, target.name))
            onReplied?.(replied, line)
        },
    })

    function submit(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault()
        if (body.trim() && !mutation.isPending) {
            mutation.mutate(body)
        }
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
        if (!target.noted) {
            // With no notes the panel says nothing of them, so the box says what that means.
            placeholder = `No notes yet: its runs follow its prompt file alone. ${placeholder}`
        }
    } else if (target.isPublic) {
        // Only while one waits does the box ask about an untrusted review; a ticket with none has nothing to say of it.
        // The ticket's comments stay on the tracker, as its chip says on hover; this box writes to canopy alone.
        placeholder = untrusted
            ? 'Say what to do about the untrusted review. It stays in canopy, never on the ticket.'
            : 'For its next worker, as an instruction. It stays in canopy, never on the ticket.'
    }

    return (
        <form onSubmit={submit} aria-label={chore ? 'Note' : 'Reply'} className="flex flex-col gap-2 border-t p-3">
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
                    onKeyDown={sendKeys.onKeyDown}
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
                    aria-keyshortcuts={sendKeys.shortcut}
                >
                    <Send />
                    {chore ? 'Add note' : 'Reply'}
                    <SendKeycap keys={sendKeys.shortcut} />
                </Button>
            </div>
        </form>
    )
}
