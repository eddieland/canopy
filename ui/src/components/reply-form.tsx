import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Send } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { newSubmission, refreshTicket, replyTicket } from '@/api/mutations'
import { Textarea } from '@/components/input'
import { Notice } from '@/components/notice'
import { Button } from '@/components/ui/button'
import { repliedText } from '@/lib/outcomes'

// The operator's bound (DESIGN §22): the server refuses more, after stripping, rather than cut it.
const MAX_REPLY = 4000

/**
 * Answers a ticket, as `canopy reply` does. The submission id is drawn when the form is rendered and kept until a
 * reply is recorded, so sending again after an uncertain result records nothing new (DESIGN §22). On a public ticket
 * the reply stays in canopy: it is how the operator says what to do about an untrusted reviewer's comments (D089).
 */
export function ReplyForm({
    ticketKey,
    waiting,
    isPublic = false,
}: {
    ticketKey: string
    waiting: number | null
    isPublic?: boolean
}) {
    const client = useQueryClient()
    const [body, setBody] = useState('')
    const [submission, setSubmission] = useState(newSubmission)
    const [said, setSaid] = useState<string | null>(null)
    const mutation = useMutation({
        mutationFn: (text: string) => replyTicket(ticketKey, text, submission),
        onSuccess: (replied) => {
            setSaid(repliedText(ticketKey, replied))
            setBody('')
            setSubmission(newSubmission())
            void refreshTicket(client, ticketKey)
        },
    })

    function submit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault()
        if (body.trim()) mutation.mutate(body)
    }

    return (
        <form onSubmit={submit} aria-label="Reply" className="flex flex-col gap-2 border-t p-3">
            <label className="flex flex-col gap-1.5">
                <span className="panel-label">
                    {waiting !== null ? `Your answer to message ${waiting}` : 'Your reply'}
                </span>
                <Textarea
                    name="body"
                    value={body}
                    maxLength={MAX_REPLY}
                    onChange={(event) => setBody(event.target.value)}
                    placeholder={
                        isPublic
                            ? 'Stays in canopy, never on the ticket. Say what to do about an untrusted review.'
                            : 'The next worker reads it as an instruction.'
                    }
                />
            </label>
            <div className="flex items-center justify-between gap-3">
                <Notice error={mutation.error}>{said}</Notice>
                <span className="ml-auto readout text-xs text-muted-foreground">
                    {body.length}/{MAX_REPLY}
                </span>
                <Button type="submit" disabled={mutation.isPending || !body.trim()}>
                    <Send />
                    Reply
                </Button>
            </div>
        </form>
    )
}
