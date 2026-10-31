import { useEffect, useEffectEvent, useState } from 'react'

import { StartTicket } from '@/components/start-ticket'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { dialogOpen, isBareKey, isTextField } from '@/lib/shortcut'
import { cn } from '@/lib/utils'

/**
 * The Start a ticket dialog (ui/DESIGN.md, The ticket dialog): the tickets page's form (`StartTicket`) from any
 * page, placed as the jump palette is. `T`, with no modifier, from anywhere but a text field or the plan editor, opens
 * it with the focus in the key field; it never opens over another dialog. A ticket that starts closes it, and the
 * form opens the ticket's page; a refusal keeps it open, naming its guard.
 */
export function TicketDialog() {
    const [open, setOpen] = useState(false)

    const onKey = useEffectEvent((event: KeyboardEvent) => {
        if (isBareKey('t', event) && !isTextField(event.target) && !dialogOpen()) {
            event.preventDefault()
            setOpen(true)
        }
    })
    useEffect(() => {
        globalThis.addEventListener('keydown', onKey)
        return () => {
            globalThis.removeEventListener('keydown', onKey)
        }
    }, [])

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogContent className="max-w-xl" data-testid="ticket-dialog">
                {/* A panel's header, as on the tickets page, inside the box's border. */}
                <div
                    className={cn(
                        'flex min-h-9 items-center border-b bg-surface-raised/50 px-3 py-0.5',
                        'rounded-t-[calc(var(--radius-md)-1px)]',
                    )}
                >
                    <DialogTitle className="panel-label font-medium text-foreground">Start a ticket</DialogTitle>
                </div>
                <DialogDescription className="sr-only">
                    Start a ticket privately by its key: no queue label needed, and its conversation stays in canopy
                </DialogDescription>
                {open && (
                    <StartTicket
                        focus
                        onStarted={() => {
                            setOpen(false)
                        }}
                    />
                )}
            </DialogContent>
        </Dialog>
    )
}
