import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import { Send } from 'lucide-react'
import { useId, useState } from 'react'
import type { SubmitEvent } from 'react'

import {
    messageRun,
    newSubmission,
    refreshChore,
    refreshMessaged,
    refreshTask,
    refreshTicket,
    replyChore,
    replyTask,
    replyTicket,
} from '@/api/mutations'
import type { Replied } from '@/api/types'
import { MarkdownField } from '@/components/markdown-field'
import { Notice } from '@/components/notice'
import { SendKeycap } from '@/components/send-keycap'
import { Button } from '@/components/ui/button'
import { notedText, repliedText, runMessagedText, taskRepliedText } from '@/lib/outcomes'
import { draftKey, keepDraft, readDraft } from '@/lib/reply-draft'
import { useSendKeys } from '@/lib/send-key'
import { cn } from '@/lib/utils'

// The operator's bound (DESIGN §22): the server refuses more, after stripping, rather than cut it.
const MAX_REPLY = 4000
// How long a reply grows before its count shows: near the limit, where the count is worth reading.
const NEAR_LIMIT = MAX_REPLY * 0.8

/**
 * What a reply goes to: a ticket, public or private; a chore, whose next runs read it as a note (DESIGN §19), and
 * which may have none yet (`noted` false), so its runs follow its prompt file alone; a task, whose next run it
 * starts as the operator's next instruction (DESIGN §36), or, from a run of it still `running`, that run hears; or a
 * running worker's or planner's run, which hears it as a message in the operator's own words (DESIGN §44).
 */
export type ReplyTarget =
    | { kind: 'ticket'; key: string; isPublic: boolean }
    | { kind: 'chore'; name: string; noted: boolean }
    | { kind: 'task'; id: number; running?: boolean }
    | { kind: 'run'; id: number }

/**
 * Answers a ticket, as `canopy reply` does, notes something to a chore, as `canopy reply chore:NAME` does, gives a
 * task its next instruction, as `canopy reply task:N` does, or sends a running run a message, as `canopy reply run:ID`
 * does with words. The
 * submission id is drawn when the form is rendered and kept until a reply is recorded, so sending again after an
 * uncertain result records nothing new (DESIGN §22). Until it is recorded, what is written is kept with its submission
 * id for the tab's life (`src/lib/reply-draft.ts`), so a sign-out mid-reply loses nothing. On a public ticket the
 * reply stays in canopy: it is how the operator says what to do about an untrusted reviewer's comments (D089).
 *
 * It is always open, on any ticket, any chore, and any task not stopped, so a note for the next worker is never a click
 * away; what it is for is said by its label and placeholder: the message it answers (`waiting`), an untrusted review
 * waiting on the go-ahead (`untrusted`), where a reply on a public ticket goes, or that a task's next run reads it.
 * It is written in a `MarkdownField`, in the Markdown the conversation draws, with a Preview of how it will read there.
 *
 * `onReplied` hears each reply recorded, after the form has said what it did, with that line: the attention page moves
 * on to the next item that waits on the operator.
 */
export function ReplyForm({
    target,
    waiting = null,
    untrusted = false,
    onReplied,
    className,
}: {
    target: ReplyTarget
    waiting?: number | null
    untrusted?: boolean
    onReplied?: (replied: Replied, said: string) => void
    className?: string
}) {
    const client = useQueryClient()
    const sendKeys = useSendKeys()
    const fieldId = useId()
    const stored = draftKey(subjectOf(target))
    // The parent keys the form by its subject, so the draft is read once for it, on mount.
    const [draft] = useState(() => readDraft(stored))
    const [body, setBody] = useState(draft?.body ?? '')
    const [submission, setSubmission] = useState(() => draft?.submission ?? newSubmission())
    const [said, setSaid] = useState<string | null>(null)
    const mutation = useMutation({
        mutationFn: async (text: string): Promise<{ replied: Replied; line: string }> => {
            switch (target.kind) {
                case 'ticket': {
                    const replied = await replyTicket(target.key, text, submission)
                    return { replied, line: repliedText(target.key, replied) }
                }
                case 'chore': {
                    const replied = await replyChore(target.name, text, submission)
                    return { replied, line: notedText(target.name, replied) }
                }
                case 'task': {
                    const replied = await replyTask(target.id, text, submission)
                    return { replied, line: taskRepliedText(target.id, replied) }
                }
                case 'run': {
                    // A message answers no question (DESIGN §44), so the reply it is to `onReplied` answers none.
                    const messaged = await messageRun(target.id, text, submission)
                    const replied = { message_id: messaged.message_id, answers: null, new: messaged.new }
                    return { replied, line: runMessagedText(target.id, messaged) }
                }
            }
        },
        onSuccess: ({ replied, line }) => {
            setSaid(line)
            setBody('')
            setSubmission(newSubmission())
            keepDraft(stored, { body: '', submission })
            void refresh(client, target)
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
    const run = target.kind === 'run'
    // The form's noun, as its label names it.
    let noun = chore ? 'Note' : 'Reply'
    if (run) {
        noun = 'Message'
    }
    let label = noun
    if (waiting !== null) {
        label = `Reply to message ${waiting}`
    }
    let placeholder = 'The next worker reads it as an instruction.'
    if (run) {
        placeholder =
            'In your own words, such as that its scope changed. Its agent hears that it waits on its next tool call.'
    } else if (target.kind === 'task' && target.running === true) {
        placeholder =
            'Its running agent hears that it waits on its next tool call, and reads it as your next instruction.'
    } else if (target.kind === 'task') {
        placeholder = 'Its next run reads it as your next instruction, with the conversation so far.'
    } else if (chore) {
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

    // On a ticket, a question waiting pairs with the form in its own tint, so the two read as one; a task's page draws
    // its band around the form instead (`TaskAnswer`).
    const answering = waiting !== null && target.kind === 'ticket'
    const near = body.length >= NEAR_LIMIT
    return (
        <form
            onSubmit={submit}
            aria-label={noun}
            className={cn(
                'flex flex-col gap-2 border-t p-3',
                answering && 'border-status-blocked/40 bg-status-blocked/8',
                className,
            )}
        >
            <div className="flex flex-col gap-1.5">
                <label htmlFor={fieldId} className={cn('panel-label', answering && 'text-status-blocked')}>
                    {label}
                </label>
                <MarkdownField
                    id={fieldId}
                    name="body"
                    value={body}
                    maxLength={MAX_REPLY}
                    onValueChange={(next) => {
                        setBody(next)
                        keepDraft(stored, { body: next, submission })
                    }}
                    onKeyDown={sendKeys.onKeyDown}
                    placeholder={placeholder}
                    pullRequests
                    className="focus-within:bg-accent/8"
                />
            </div>
            <div className="flex items-center justify-between gap-3">
                <Notice error={mutation.error}>{said}</Notice>
                {near && (
                    <span className="ml-auto readout text-xs text-muted-foreground">
                        {body.length}/{MAX_REPLY}
                    </span>
                )}
                <Button
                    className={cn(!near && 'ml-auto')}
                    type="submit"
                    disabled={mutation.isPending || !body.trim()}
                    aria-keyshortcuts={sendKeys.shortcut}
                >
                    <Send />
                    {buttonText(target)}
                    <SendKeycap keys={sendKeys.shortcut} />
                </Button>
            </div>
        </form>
    )
}

/** What the form's button says: a chore takes a note, a run is sent a message, anything else a reply. */
function buttonText(target: ReplyTarget): string {
    switch (target.kind) {
        case 'chore': {
            return 'Add note'
        }
        case 'run': {
            return 'Send'
        }
        case 'ticket':
        case 'task': {
            return 'Reply'
        }
    }
}

/** Where the draft of a reply to `target` is kept: `ticket:ABC-1`, `chore:deps`, `task:4`, or `run:41`. */
function subjectOf(target: ReplyTarget): string {
    switch (target.kind) {
        case 'ticket': {
            return `ticket:${target.key}`
        }
        case 'chore': {
            return `chore:${target.name}`
        }
        case 'task': {
            return `task:${target.id}`
        }
        case 'run': {
            return `run:${target.id}`
        }
    }
}

/** Reads what a reply to `target` changed again now, rather than wait for the stream to say it changed. */
function refresh(client: QueryClient, target: ReplyTarget): Promise<void> {
    switch (target.kind) {
        case 'ticket': {
            return refreshTicket(client, target.key)
        }
        case 'chore': {
            return refreshChore(client, target.name)
        }
        case 'task': {
            return refreshTask(client, target.id)
        }
        case 'run': {
            return refreshMessaged(client, target.id)
        }
    }
}
