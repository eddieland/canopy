import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import { Send } from 'lucide-react'
import { useId, useState } from 'react'
import type { SubmitEvent } from 'react'

import {
    messageRun,
    newSubmission,
    refreshChore,
    refreshTask,
    refreshTicket,
    replyChore,
    replyTask,
    replyTicket,
} from '@/api/mutations'
import { runsQuery } from '@/api/queries'
import type { Replied, Run } from '@/api/types'
import { MarkdownField } from '@/components/markdown-field'
import { Notice } from '@/components/notice'
import { SendKeycap } from '@/components/send-keycap'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { notedText, repliedText, runMessagedText, taskRepliedText } from '@/lib/outcomes'
import { runRef } from '@/lib/refs'
import { draftKey, keepDraft, readDraft } from '@/lib/reply-draft'
import { workingOn } from '@/lib/run-state'
import { useSendKeys } from '@/lib/send-key'
import { cn } from '@/lib/utils'

// The operator's bound (DESIGN §22): the server refuses more, after stripping, rather than cut it.
const MAX_REPLY = 4000
// How long a reply grows before its count shows: near the limit, where the count is worth reading.
const NEAR_LIMIT = MAX_REPLY * 0.8
// What the box that tells the running run says on hover.
const TELL_NOW =
    'Off, the next run reads your reply. On, the run working now hears on its next tool call that you wrote.'

/**
 * What a reply goes to: a ticket, public or private; a chore, whose next runs read it as a note (DESIGN §19), and
 * which may have none yet (`noted` false), so its runs follow its prompt file alone; or a task, whose next run it
 * starts as the operator's next instruction (DESIGN §36).
 */
export type ReplyTarget =
    | { kind: 'ticket'; key: string; isPublic: boolean }
    | { kind: 'chore'; name: string; noted: boolean }
    | { kind: 'task'; id: number }

/**
 * Answers a ticket, as `canopy reply` does, notes something to a chore, as `canopy reply chore:NAME` does, or gives a
 * task its next instruction, as `canopy reply task:N` does. The
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
 * While a worker or a planner runs on the ticket, the one its conversation shows working, a box beside the button
 * offers to tell that run now (DESIGN §44): checked, the reply is a message to the run, as `canopy reply run:ID` sends
 * one, recorded on the ticket all the same, which its agent hears of on its next tool call. It is off by default, and
 * after each send, since a reply mid-run is mostly meant for the next run, and steering an agent mid-edit is a choice.
 * It is not offered while the form answers an open question, and goes once the run ends: a send it refused as ended
 * keeps the draft and its submission id, so sending again goes to the ticket and records one message.
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
    // The run the box offers to tell now, and the one it was checked for: never kept, so each reply starts unchecked.
    const running = useRunning(target, waiting)
    const [toRun, setToRun] = useState<number | null>(null)
    const telling = toRun !== null && running?.id === toRun ? running : undefined
    const mutation = useMutation({
        mutationFn: async (text: string): Promise<{ replied: Replied; line: string }> => {
            switch (target.kind) {
                case 'ticket': {
                    if (telling !== undefined) {
                        // A message answers no question (DESIGN §44), so the reply it is to `onReplied` answers none.
                        const messaged = await messageRun(telling.id, text, submission)
                        const replied = { message_id: messaged.message_id, answers: null, new: messaged.new }
                        return { replied, line: runMessagedText(telling.id, messaged) }
                    }
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
            }
        },
        onSuccess: ({ replied, line }) => {
            setSaid(line)
            setBody('')
            setSubmission(newSubmission())
            setToRun(null)
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
    // The form's noun, as its button names it.
    let label = chore ? 'Note' : 'Reply'
    if (waiting !== null) {
        label = `Reply to message ${waiting}`
    }
    let placeholder = 'The next worker reads it as an instruction.'
    if (telling !== undefined) {
        const run = `Run ${telling.id}`
        placeholder = `${run} hears on its next tool call that you wrote, and reads it through canopy's tool.`
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
            aria-label={chore ? 'Note' : 'Reply'}
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
                {running !== undefined && (
                    <TellNow
                        run={running}
                        checked={telling !== undefined}
                        disabled={mutation.isPending}
                        onCheckedChange={(checked) => setToRun(checked ? running.id : null)}
                        className={cn(!near && 'ml-auto')}
                    />
                )}
                <Button
                    className={cn(!near && running === undefined && 'ml-auto')}
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

/**
 * The run working a ticket now that its reply form may tell at once: its worker or planner, the newest when there are
 * two, as the conversation shows them working. None for a chore or a task, nor while the form answers an open question.
 */
function useRunning(target: ReplyTarget, waiting: number | null): Run | undefined {
    const runs = useQuery(runsQuery).data ?? []
    if (target.kind !== 'ticket' || waiting !== null) {
        return undefined
    }
    return workingOn(runs, target.key).at(-1)
}

/** The box beside the button that sends a ticket's reply to its running run now, rather than to its next run. */
function TellNow({
    run,
    checked,
    disabled,
    onCheckedChange,
    className,
}: {
    run: Run
    checked: boolean
    disabled: boolean
    onCheckedChange: (checked: boolean) => void
    className?: string
}) {
    const id = useId()
    return (
        // Kept whole: when the row is tight the notice gives, never the label's words.
        <span className={cn('flex shrink-0 items-center gap-1.5 whitespace-nowrap', className)}>
            <Checkbox
                id={id}
                checked={checked}
                disabled={disabled}
                onCheckedChange={(next) => onCheckedChange(next === true)}
            />
            <label htmlFor={id} className="text-xs" title={TELL_NOW}>
                Tell <span className="font-mono">{runRef(run.id)}</span> now
            </label>
        </span>
    )
}

/** Where the draft of a reply to `target` is kept: `ticket:ABC-1`, `chore:deps`, or `task:4`. */
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
    }
}
