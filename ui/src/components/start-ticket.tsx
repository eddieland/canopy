import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Play } from 'lucide-react'
import type { SubmitEvent } from 'react'

import { refreshTicket, startTicket } from '@/api/mutations'
import { Input } from '@/components/input'
import { Notice } from '@/components/notice'
import { Button } from '@/components/ui/button'

/** Starts a ticket privately by its key (DESIGN §22), then opens its page. */
export function StartTicket() {
    const client = useQueryClient()
    const navigate = useNavigate()
    const mutation = useMutation({
        mutationFn: startTicket,
        onSuccess: (_started, key) => {
            void refreshTicket(client, key)
            void navigate({ to: '/tickets/$key', params: { key } })
        },
    })

    function submit(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault()
        const key = new FormData(event.currentTarget).get('key')
        if (typeof key === 'string' && key.trim()) {
            mutation.mutate(key.trim())
        }
    }

    return (
        <form onSubmit={submit} aria-label="Start a ticket" className="flex flex-col gap-2 p-3">
            <div className="flex items-center gap-2">
                <Input name="key" placeholder="PROJ-123" aria-label="Ticket key" className="max-w-56 font-mono" />
                <Button type="submit" variant="outline" disabled={mutation.isPending}>
                    <Play />
                    Start privately
                </Button>
            </div>
            <Notice error={mutation.error}>
                No queue label needed. Its conversation stays in canopy: nothing reaches the ticket.
            </Notice>
        </form>
    )
}
